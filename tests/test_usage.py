"""The anonymous usage count (soundboard/core/usage.py): on for new installs, off for
copies from before it existed, off when the installer's box is unticked, never sent
from source, without a key or while switched off, and it says only what SECURITY.md
says it does."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from soundboard import __version__, i18n
from soundboard.core import app, applog, reset, usage
from soundboard.sounds import library
from soundboard.online import net
from soundboard.sounds.library import Config
from test_mainwindow import window  # noqa: F401 - the real window, offscreen


@pytest.fixture
def sent(app_dir, monkeypatch):
    """The requests the count would make (nothing really goes online)."""
    out = []

    class Answer:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None, feature=""):
        out.append((req, feature))
        return Answer()
    monkeypatch.setattr(net, "urlopen", urlopen)
    monkeypatch.setattr(usage, "TOKEN", "count-only-key")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("ONIONBOARD_NO_STATS", raising=False)
    monkeypatch.setattr(usage, "threading", SimpleNamespace(Thread=_Inline))
    monkeypatch.setattr(usage, "_used", set())
    monkeypatch.setattr(usage, "_open_mark", None)
    net.configure_features()
    yield out
    net.configure_features()


class _Inline:
    def __init__(self, target, **kw):
        self.target = target

    def start(self):
        self.target()

    def join(self, timeout=None):
        pass


ABOUT = ("age/", "route/", "sounds/", "played/", "open/", "lang/", "lang-windows/",
         "used/", "os/", "launches/", "downloads/", "theme/", "achievements/",
         "ach-score/")


def _hits(req, about=False) -> list[dict]:
    """The hits sent; without the daily picture of how it's used unless `about`."""
    hits = json.loads(req.data.decode("utf-8"))["hits"]
    return [h for h in hits if about or not h["path"].startswith(ABOUT)]


def test_a_new_install_counts_once_a_day(sent):
    cfg = Config()
    saved = []
    usage.maybe_send(cfg, lambda apply: (apply(), saved.append(1)))
    assert len(sent) == 1 and saved == [1]
    req, feature = sent[0]
    assert feature == usage.FEATURE and req.full_url == usage.ENDPOINT
    hits = _hits(req)
    assert [h["path"] for h in hits] == [f"/app/{__version__}", "first-start"]
    assert {h["session"] for h in hits} == {cfg.stats_id} and len(cfg.stats_id) == 32
    # the same short tag on every count, so one person's days link up (not the ID itself)
    assert {h["ref"] for h in hits} == {usage.user_tag(cfg.stats_id)}
    assert usage.user_tag(cfg.stats_id) != cfg.stats_id and len(usage.user_tag("x")) == 14
    # nothing but these fields leaves the PC
    assert all(set(h) <= {"path", "title", "event", "session", "ref"} for h in hits)
    usage.maybe_send(cfg)   # the same day: nothing
    assert len(sent) == 1
    cfg.stats_sent -= usage.EVERY_S   # a day later: only the daily one
    usage.maybe_send(cfg)
    assert [h["path"] for h in _hits(sent[1][0])] == [f"/app/{__version__}"]


@pytest.mark.parametrize("answer, path", [
    ("youtube", "first-start/heard-youtube"),
    ("  You Tube ", "first-start/heard-youtube"),
    ("my friends", "first-start/heard-friend"),
    ("Discord server", "first-start/heard-other-discord-server"),
    ("twitch.tv", "first-start/heard-other-twitch-tv"),
    ("", "first-start"),
    # typed answers that don't read like a name are dropped, not sent
    ("me@example.com", "first-start"),
    ("021 555 1234", "first-start"),
    ("https://example.com/x", "first-start"),
    ("asdfghjkl", "first-start"),
    ("<script>", "first-start"),
    ("one two three four", "first-start"),
    ("a" * 40, "first-start"),
])
def test_first_start_says_where_they_heard(sent, answer, path):
    cfg = Config(stats_heard=answer)
    usage.maybe_send(cfg)
    assert [h["path"] for h in _hits(sent[0][0])] == [f"/app/{__version__}", path]
    cfg.stats_sent -= usage.EVERY_S   # only ever once
    usage.maybe_send(cfg)
    assert [h["path"] for h in _hits(sent[1][0])] == [f"/app/{__version__}"]


def test_the_count_waits_while_the_pc_is_short_of_memory(sent, monkeypatch):
    from soundboard.core import hangwatch
    monkeypatch.setattr(usage, "MEMORY_FULL", 90)   # conftest's is never reached
    monkeypatch.setattr(hangwatch, "memory_load", lambda: 93)
    cfg = Config()
    usage.maybe_send(cfg)
    assert sent == [] and not cfg.stats_sent   # still due: a later check sends it
    usage.maybe_send(cfg, event="update-now/x")   # an event goes anyway
    assert len(sent) == 1
    monkeypatch.setattr(hangwatch, "memory_load", lambda: 89)
    usage.maybe_send(cfg)
    assert len(sent) == 2 and cfg.stats_sent


def test_update_now_is_one_event(sent):
    cfg = Config(stats_sent=1.0)
    usage.maybe_send(cfg, event=usage.update_event("9.9.9"))
    (hit,) = _hits(sent[0][0])
    assert hit["event"] and hit["path"] == f"update-now/{__version__}-to-9.9.9"
    assert cfg.stats_sent == 1.0   # not the daily one


@pytest.mark.parametrize("why", ["switched off", "offline", "source", "no key", "dev pc"])
def test_nothing_is_sent(sent, monkeypatch, why):
    cfg = Config()
    if why == "switched off":
        net.configure_features(["usage_stats"])
    elif why == "offline":
        net.configure_features(offline=True)
    elif why == "source":
        monkeypatch.delattr(sys, "frozen")
    elif why == "dev pc":
        monkeypatch.setenv("ONIONBOARD_NO_STATS", "1")
    else:
        monkeypatch.setattr(usage, "TOKEN", "")
    usage.maybe_send(cfg)
    usage.maybe_send(cfg, event="update-now/x")
    assert sent == [] and cfg.stats_sent == 0.0


def test_a_failed_send_tries_again_next_time(sent, monkeypatch):
    def down(*a, **k):
        raise OSError("no internet")
    monkeypatch.setattr(net, "urlopen", down)
    cfg = Config()
    usage.maybe_send(cfg)
    assert cfg.stats_sent == 0.0


def test_new_installs_are_on_and_older_configs_are_off(app_dir):
    assert Config.load().net_off == []   # a first start
    Config(net_off=["radio"]).save()
    assert Config.load().net_off == ["radio"]
    raw = Config(net_off=["radio"]).to_raw()
    raw.pop("stats_id")   # saved by a version from before the count
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    cfg = Config.load()
    assert cfg.net_off == ["radio", "usage_stats"]
    cfg.save()   # and it stays off once this version saved it
    cfg.net_off.remove("usage_stats")   # until they switch it on
    cfg.save()
    assert Config.load().net_off == ["radio"]


def test_an_old_config_without_privacy_settings_is_off_too(app_dir):
    raw = Config().to_raw()
    for k in (*library.PRIVACY_KEYS, "stats_id"):
        raw.pop(k)
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    assert "usage_stats" in Config.load().net_off


def test_a_settings_reset_never_switches_it_back_on(app_dir):
    """Nor any other switch: a reset keeps how the app goes online."""
    Config(net_off=["usage_stats", "radio"]).save()
    reset.reset([reset.SETTINGS])
    assert Config.load().net_off == ["usage_stats", "radio"]


@pytest.fixture
def cli(app_dir, monkeypatch):
    monkeypatch.setattr(app, "APP_DIR", app_dir)
    monkeypatch.setattr(applog, "setup", lambda d: d / "log")
    monkeypatch.setattr(net, "urlopen", lambda *a, **k: pytest.fail("went online"))
    yield app_dir


def test_the_installer_box(cli):
    assert app.set_usage_count(False) == 0   # unticked on a first install
    cfg = Config.load()
    assert cfg.net_off == ["usage_stats"] and cfg.setup_done is False
    assert app.set_usage_count(True) == 0   # ticked on a later install
    assert Config.load().net_off == []
    Config(net_off=["radio"], sound_vol=0.42).save()
    assert app.set_usage_count(False) == 0
    cfg = Config.load()
    assert cfg.net_off == ["radio", "usage_stats"] and cfg.sound_vol == 0.42
    assert app.set_usage_count(True, "Reddit") == 0   # the "where did you hear" page
    cfg = Config.load()
    assert cfg.stats_heard == "Reddit" and cfg.net_off == ["radio"]
    assert app.set_usage_count(True) == 0   # no answer keeps the last one
    assert Config.load().stats_heard == "Reddit"


def _body(req) -> dict:
    return json.loads(req.data.decode("utf-8"))


def test_unticking_sends_one_anonymous_opt_out(sent, app_dir, monkeypatch):
    """Count me in going from on to off says so once, with nothing that ties it to the
    person (no ID, tag or session), then nothing more."""
    monkeypatch.setattr(app, "APP_DIR", app_dir)
    monkeypatch.setattr(applog, "setup", lambda d: d / "log")
    assert app.set_usage_count(False) == 0          # unticked on a first install
    ((req, feature),) = sent
    assert feature == usage.FEATURE and _body(req)["no_sessions"] is True
    assert _body(req)["hits"] == [{"path": "opt-out/installer", "title": "opt-out/installer",
                                   "event": True}]
    assert Config.load().net_off == ["usage_stats"] and not Config.load().stats_id
    net.configure_features()
    assert app.set_usage_count(False) == 0          # unticked again on an update: already off
    assert len(sent) == 1
    Config(net_offline=True).save()                 # Offline mode: never
    assert app.set_usage_count(False) == 0 and len(sent) == 1
    net.configure_features()
    assert not usage.opt_out("somewhere-else") and len(sent) == 1
    assert usage.opt_out("settings") and _body(sent[-1][0])["hits"][0]["path"] == "opt-out/settings"


def test_no_opt_out_in_tor_mode(sent, monkeypatch):
    """SECURITY.md: the opt-out is never sent in Tor mode, from Settings either (the
    installer's path already checked; Settings' switch didn't)."""
    monkeypatch.setattr(net, "_mode", net.TOR)
    assert not usage.opt_out("settings") and not sent
    monkeypatch.setattr(net, "_mode", net.DIRECT)
    assert usage.opt_out("settings") and len(sent) == 1


def test_update_now_fetches_its_own_copy_of_the_installer():
    from soundboard.core import updates

    def asset(name, sha):
        return {"name": name, "browser_download_url": updates.DOWNLOADS + "v9/" + name,
                "digest": "sha256:" + sha * 64, "size": 5}
    both = {"assets": [asset(updates.ASSET, "a"), asset(updates.UPDATE_ASSET, "b")]}
    assert updates._installer(both)[0].endswith("/" + updates.UPDATE_ASSET)
    old = {"assets": [asset(updates.ASSET, "a")]}   # a release from before it
    assert updates._installer(old) == (updates.DOWNLOADS + "v9/" + updates.ASSET, "a" * 64, 5)


# -- tabs, problems and uninstall ------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_pending():
    usage._pending.clear()
    usage._warned.clear()
    usage._failed.clear()
    yield
    usage._pending.clear()
    usage._warned.clear()
    usage._failed.clear()


def test_the_daily_count_says_which_tabs_were_opened_then_forgets_them(sent):
    cfg = Config(stats_sent=1.0)
    usage.tab_opened(cfg, "radio")
    usage.tab_opened(cfg, "voice")
    usage.tab_opened(cfg, "radio")          # once
    usage.tab_opened(cfg, "my secret tab")  # not a tab we know: never sent
    usage.maybe_send(cfg)
    paths = [h["path"] for h in _hits(sent[0][0])]
    assert paths == [f"/app/{__version__}", "tab/radio", "tab/voice"]
    assert cfg.stats_tabs == []
    usage.tab_opened(cfg, "sounds")
    usage.maybe_send(cfg)                  # the same day: kept for tomorrow
    assert len(sent) == 1 and cfg.stats_tabs == ["sounds"]


def test_the_send_thread_never_writes_the_settings(sent, monkeypatch):
    """The UI thread keeps adding to stats_* while a count is on its way: the thread
    only sends, and what it sent is cleared on the UI thread (on_sent), so a tab opened
    or a download counted meanwhile is still counted next time."""
    import threading
    writers = []

    class Watched(Config):
        def __setattr__(self, name, value):
            if name.startswith("stats_"):
                writers.append((name, threading.current_thread() is threading.main_thread()))
            super().__setattr__(name, value)
    monkeypatch.setattr(usage, "threading", threading)   # a real thread this time
    go, done, queued = threading.Event(), threading.Event(), []
    real = net.urlopen

    def slow(req, timeout=None, feature=""):
        go.wait(5)
        return real(req, timeout, feature)
    monkeypatch.setattr(net, "urlopen", slow)
    cfg = Watched(stats_sent=1.0)
    usage.tab_opened(cfg, "voice")
    usage.downloaded(cfg, "https://www.youtube.com/watch?v=x", "link", "add", True)
    writers.clear()
    usage.maybe_send(cfg, lambda apply: (queued.append(apply), done.set()))
    usage.tab_opened(cfg, "radio")           # the UI thread, while it's on its way
    usage.downloaded(cfg, "https://www.youtube.com/watch?v=y", "link", "add", True)
    go.set()
    assert done.wait(5)
    assert all(on_ui for __, on_ui in writers), writers   # the thread wrote nothing
    assert cfg.stats_tabs == ["voice", "radio"] and cfg.stats_downloads == 2
    (apply,) = queued
    apply()                                  # on the UI thread (the main window queues it)
    assert all(on_ui for __, on_ui in writers)
    assert cfg.stats_tabs == ["radio"] and cfg.stats_downloads == 1 and cfg.stats_sent > 1
    cfg.stats_sent -= usage.EVERY_S          # the next count: the tab opened meanwhile
    monkeypatch.setattr(usage, "threading", SimpleNamespace(Thread=_Inline))
    usage.maybe_send(cfg)
    assert "tab/radio" in [h["path"] for h in _hits(sent[-1][0])]


def test_kept_events_added_while_a_count_is_on_its_way_stay(sent):
    cfg = Config(stats_sent=1e18, stats_pending=["warned/a"])   # daily not due
    queued = []
    usage.maybe_send(cfg, queued.append)
    usage.note("warned/b")                   # meanwhile
    usage.remember(cfg)
    queued[0]()
    assert cfg.stats_pending == ["warned/b"]


def _report(app_dir, name, text, mtime):
    import os
    folder = app_dir / applog.REPORTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_text(text, encoding="utf-8")
    os.utime(f, (mtime, mtime))
    return f


def test_new_crash_and_freeze_reports_are_counted_once_never_sent(sent, app_dir):
    cfg = Config(stats_sent=1e18, stats_problems_seen=1000.0)   # daily not due
    _report(app_dir, "crash-old.txt", "Onion Board crash report\nVersion:  1.0.0\n", 900)
    _report(app_dir, "crash-a.txt", "Onion Board crash report\nVersion:  1.9.6\n"
            "Fatal:    yes (the app could not continue)\n\nError\nC:\\Users\\Bob\\x", 2000)
    _report(app_dir, "crash-b.txt", "Onion Board crash report\nVersion:  1.9.6\n", 2001)
    _report(app_dir, "crash-c.txt", "Onion Board froze for 12 s\nVersion:  1.9.7\n", 2002)
    saved = []
    usage.maybe_send(cfg, lambda apply: (apply(), saved.append(1)), app_dir=app_dir)
    hits = _hits(sent[0][0])
    assert [h["path"] for h in hits] == ["crash/1.9.6", "error/1.9.6", "freeze/1.9.7"]
    assert "Bob" not in sent[0][0].data.decode()
    assert cfg.stats_problems_seen == 2002 and saved == [1]
    usage.maybe_send(cfg, app_dir=app_dir)   # nothing new: nothing sent
    assert len(sent) == 1


def test_the_reports_folder_is_read_on_the_counts_thread(sent, app_dir, monkeypatch):
    """maybe_send runs on the UI thread a minute after each saved report, so on a PC
    that's already struggling: listing and reading the reports goes on the send's
    thread, and the window only gathers what's in memory."""
    import threading
    monkeypatch.setattr(usage, "threading", threading)   # a real thread this time
    _report(app_dir, "crash-a.txt", "Onion Board froze for 12 s\nVersion:  1.9.7\n", 2000)
    readers, real, done = [], usage.problems, threading.Event()

    def problems(*a, **k):
        readers.append(threading.current_thread() is threading.main_thread())
        return real(*a, **k)
    monkeypatch.setattr(usage, "problems", problems)
    cfg = Config(stats_sent=1e18, stats_problems_seen=1000.0)   # daily not due
    queued = []
    usage.maybe_send(cfg, lambda apply: (queued.append(apply), done.set()), app_dir=app_dir)
    assert done.wait(5)
    assert readers == [False]
    assert [h["path"] for h in _hits(sent[0][0])] == ["freeze/1.9.7"]
    queued[0]()   # on the UI thread
    assert cfg.stats_problems_seen == 2000


def _real_report(where_from: str) -> str:
    """A report as applog writes it, for an error raised in a soundboard file."""
    try:
        exec(compile("def f():\n    raise KeyError('D:/private/secret.wav')\nf()",
                     where_from, "exec"), {})
    except KeyError:
        import sys
        rep = applog.build_report(sys.exc_info(), where="tick")
    return rep.text.replace(f"Version:  {applog._state['version']}", "Version:  1.9.8")


def test_problem_events_say_where_in_our_code_never_the_message(tmp_path):
    f = tmp_path / "crash-x.txt"
    src = "D:\\private\\code\\soundboard\\audio\\engine.py"
    f.write_text(_real_report(src) + "\n\nLast 60 log lines\n------\n"
                 '  File "C:\\soundboard\\ui\\other.py", line 7, in g\nOSError: x\n',
                 encoding="utf-8")
    assert usage._report_event(f) == ("error/1.9.8/KeyError@soundboard/audio/engine.py:2"
                                      "<soundboard/audio/engine.py:3")   # and its caller
    # the freeze from a real 1.9.7 report: its deepest line of our own code
    f.write_text("Onion Board froze for 6 s\nVersion:  1.9.7\nTime:  x\n\n"
                 "What it was doing\n-----------------\n"
                 '  File "main.py", line 22, in <module>\n'
                 '  File "soundboard\\ui\\window\\mainwindow.py", line 5898, in tick\n'
                 '  File "soundboard\\mic\\directmic.py", line 184, in make_ring\n'
                 '  File "pathlib\\_local.py", line 515, in stat\n', encoding="utf-8")
    assert usage._report_event(f) == ("freeze/1.9.7@soundboard/mic/directmic.py:184"
                                      "<soundboard/ui/window/mainwindow.py:5898~_local.stat")


def test_a_freeze_says_where_the_window_was_never_another_thread(tmp_path):
    """hangwatch.py lists every other thread after the window's own stack; the
    place sent is the window's, and a thread start is blamed on its caller, not on
    threadnames.py's wrapper around Thread.start."""
    f = tmp_path / "freeze-x.txt"
    f.write_text("Onion Board froze for 6 s\nVersion:  1.9.20\nTime:  x\n\n"
                 "What it was doing\n-----------------\n"
                 '  File "main.py", line 22, in <module>\n'
                 '  File "soundboard\\ui\\window\\mainwindow.py", line 5898, in tick\n'
                 '  File "soundboard\\core\\threadnames.py", line 70, in named_start\n'
                 '  File "threading.py", line 999, in start\n'
                 "\nOther threads\n-------------\n"
                 'Thread "audio" (12):\n'
                 '  File "soundboard\\core\\threadnames.py", line 68, in named_run\n'
                 '  File "soundboard\\audio\\engine.py", line 400, in _loop\n'
                 'Thread "x" (13):\n'
                 '  File "soundboard\\core\\threadnames.py", line 70, in named_start\n',
                 encoding="utf-8")
    assert usage._report_event(f) == ("freeze/1.9.20@soundboard/ui/window/mainwindow.py:5898"
                                      "~threading.start")


def _freeze(f, lasted, window_cpu, others, inner='  File "threading.py", line 359, in wait\n'):
    f.write_text("Onion Board froze for 5 s\nVersion:  1.9.28\nTime:  x\n"
                 + (f"Lasted:   {lasted}\n" if lasted else "") + "\n"
                 "What it was doing\n-----------------\n"
                 '  File "D:\\private\\code\\soundboard\\ui\\window\\mainwindow.py", '
                 'line 50, in tick\n'
                 '  File "soundboard\\core\\threadnames.py", line 70, in named_start\n'
                 '  File "soundboard\\mic\\voicesdk.py", line 80, in listen\n' + inner
                 + (f"\nWindow CPU: {window_cpu}%\n" if window_cpu is not None else "")
                 + "\nOther threads\n-------------\n" + others, encoding="utf-8")


def test_a_freeze_says_its_caller_what_it_waited_in_how_long_and_who_was_busy(tmp_path):
    """Enough to tell a freeze's cause from the count alone: the caller of the stuck
    line, the library call it was stuck in, how long it lasted, and whether the
    window was working itself, waiting on a busy thread, or everyone was waiting."""
    f = tmp_path / "crash-x.txt"
    hog = ('Thread "radio" (12), 95% CPU:\n'
           '  File "soundboard\\core\\threadnames.py", line 68, in named_run\n'
           '  File "soundboard\\online\\radio.py", line 400, in _decode\n'
           'Thread "calm" (13), 0% CPU:\n'
           '  File "soundboard\\audio\\engine.py", line 9, in _loop\n')
    _freeze(f, "42 s", 1, hog)
    assert usage._report_event(f) == (
        "freeze/1.9.28@soundboard/mic/voicesdk.py:80<soundboard/ui/window/mainwindow.py:50"
        "~threading.wait/lasted-30s-2m/busy-thread@soundboard/online/radio.py:400")
    _freeze(f, "7 s", 100, hog)
    assert usage._report_event(f).endswith("/lasted-under-10s/busy-window")
    _freeze(f, "still frozen", 0, 'Thread "calm" (13), 2% CPU:\n'
            '  File "soundboard\\audio\\engine.py", line 9, in _loop\n')
    assert usage._report_event(f).endswith("~threading.wait/never-ended/idle")
    # stuck in our own line (time.sleep has no frame): no library part
    _freeze(f, "12 s", 0, "", inner="")
    assert usage._report_event(f) == ("freeze/1.9.28@soundboard/mic/voicesdk.py:80"
                                      "<soundboard/ui/window/mainwindow.py:50/lasted-10-30s/idle")
    # the whole app was held up, not the window alone (hangwatch.ALL_HELD_NOTE)
    _freeze(f, "12 s", 0, "", inner="\n(every thread was held up, this watch too)\n")
    assert usage._report_event(f).endswith("/all-held/lasted-10-30s/idle")
    # ...by a deep garbage sweep (hangwatch.GC_SWEEP_NOTE)
    _freeze(f, "12 s", 0, "", inner="\n(every thread was held up, this watch too)\n"
            "\n(a full garbage sweep over the whole app ran meanwhile: 11.8 s)\n")
    assert usage._report_event(f).endswith("/all-held/gc-sweep/lasted-10-30s/idle")
    # an older report (no Lasted / CPU lines): only what it has
    _freeze(f, "", None, hog)
    assert usage._report_event(f) == ("freeze/1.9.28@soundboard/mic/voicesdk.py:80"
                                      "<soundboard/ui/window/mainwindow.py:50~threading.wait")
    assert "private" not in usage._report_event(f)


def test_a_freeze_end_is_noted_without_counting_the_report_again(tmp_path, monkeypatch):
    import os
    from soundboard.core import applog
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    path = applog.save_freeze(5, '  File "soundboard\\audio\\engine.py", line 9, in f\n')
    assert usage._report_event(path).endswith("/never-ended")
    os.utime(path, (1_000_000, 1_000_000))
    applog.note_freeze_end(path, 23.4)
    assert path.stat().st_mtime == 1_000_000
    assert "Lasted:   23 s" in path.read_text(encoding="utf-8")
    assert usage._report_event(path).endswith("/lasted-10-30s")
    applog.note_freeze_end(path, 99)                       # once only
    assert "Lasted:   23 s" in path.read_text(encoding="utf-8")


def test_an_error_says_its_caller_and_the_library_call_it_came_from(tmp_path):
    """Two errors that end on the same line of ours (2.0.4's TypeError at
    appspanel.py:352) are told apart by who called it and what raised it, like a
    freeze; still never the message."""
    f = tmp_path / "crash-x.txt"
    f.write_text("Onion Board crash report\nVersion:  2.0.4\n\nError\n-----\n"
                 "Traceback (most recent call last):\n"
                 '  File "C:\\x\\soundboard\\ui\\apps\\appspanel.py", line 380, in setGeometry\n'
                 "    self._place(rect, True)\n"
                 '  File "C:\\x\\soundboard\\ui\\apps\\appspanel.py", line 352, in _place\n'
                 "    item.setGeometry(QRect(x, y, w, h))\n"
                 '  File "C:\\Python\\Lib\\enum.py", line 1600, in __or__\n'
                 "    raise TypeError(private)\n"
                 "TypeError: D:/private/secret.wav\n", encoding="utf-8")
    assert usage._report_event(f) == ("error/2.0.4/TypeError@soundboard/ui/apps/appspanel.py:352"
                                      "<soundboard/ui/apps/appspanel.py:380~enum.__or__")
    assert "private" not in usage._report_event(f)


def test_every_file_of_ours_counts_as_ours():
    """A problem report names the deepest of our own lines: every module of the package
    has to match the rule, however many folders down it sits."""
    from pathlib import Path

    import soundboard
    root = Path(soundboard.__file__).parent.parent
    files = [p.relative_to(root).as_posix() for p in (root / "soundboard").rglob("*.py")]
    assert files and not [f for f in files if not usage._OUR_FILE.fullmatch(f)]
    assert not [f for f in files
                if not usage._OUR_FRAME.search(f'  File "C:\\x\\{f}", line 1, in g')]


def test_problem_events_keep_paths_outside_our_package_out(tmp_path):
    f = tmp_path / "crash-x.txt"
    # an odd install folder named soundboard: deeper than our package, so not sent
    f.write_text(_real_report("D:\\soundboard\\Python\\Lib\\json\\decoder.py"),
                 encoding="utf-8")
    assert usage._report_event(f) == "error/1.9.8/KeyError~decoder.f"   # its name only
    f.write_text(_real_report("D:\\soundboard\\python\\lib\\json\\decoder.py"),
                 encoding="utf-8")
    assert usage._report_event(f) == "error/1.9.8/KeyError~decoder.f"   # lower case too
    f.write_text("Onion Board crash report\nVersion:  1.9.8\n\nError\n-----\nboom\n",
                 encoding="utf-8")
    assert usage._report_event(f) == "error/1.9.8"


def test_reports_from_before_counting_existed_arent_sent(sent, app_dir):
    cfg = Config(stats_sent=1e18)   # stats_problems_seen 0: an update to this version
    _report(app_dir, "crash-a.txt", "Onion Board crash report\nVersion:  1.9.5\n", 2000)
    usage.maybe_send(cfg, app_dir=app_dir)
    assert sent == [] and cfg.stats_problems_seen > 2000


def test_a_bug_in_a_loop_is_at_most_a_few_hits(sent, app_dir):
    cfg = Config(stats_sent=1e18, stats_problems_seen=1.0)
    for i in range(30):
        _report(app_dir, f"crash-{i:02}.txt", "Onion Board crash report\nVersion:  2.0.0\n",
                100 + i)
    usage.maybe_send(cfg, app_dir=app_dir)
    paths = [h["path"] for h in _hits(sent[0][0])]
    # the first few, then one count saying roughly how many more (20 here)
    assert len(paths) == usage.MAX_PROBLEMS + 1
    assert paths[-1] == "problems-dropped/11-50"
    assert cfg.stats_problems_seen == 129


def test_a_run_that_never_closed_itself_is_an_unclean_exit(sent, app_dir):
    assert usage.mark_running(app_dir) == ""       # first run
    assert usage.mark_running(app_dir) == f"unclean-exit/{__version__}"   # never stopped
    usage.mark_stopped(app_dir)
    assert usage.mark_running(app_dir) == ""       # stopped cleanly
    usage.note(f"unclean-exit/{__version__}")
    cfg = Config(stats_sent=1e18, stats_problems_seen=1.0)
    usage.maybe_send(cfg, app_dir=app_dir)
    assert [h["path"] for h in _hits(sent[0][0])] == [f"unclean-exit/{__version__}"]
    assert usage._pending == [] and cfg.stats_pending == []


_NATIVE = ("Windows fatal exception: access violation\n\n"
           "Current thread 0x1 (most recent call first):\n"
           '  File "soundboard\\audio\\engine.py", line 1090 in _callback\n')


def test_a_start_that_never_finished_is_counted_never_the_message(monkeypatch):
    """A run whose breadcrumb was left (bootmark.py) died during start-up: counted as
    startup-failed/<version>, with the native stacks faulthandler caught when there are
    any, or Windows' own error for that process."""
    from soundboard.core import exitwatch
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [])
    assert usage.startup_failed("/x", "1.9.28", 42, _NATIVE) == (
        "startup-failed/1.9.28/access-violation@soundboard/audio/engine.py:1090")
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [
        {"kind": "windows-error", "code": "access-violation", "module": "Qt6Core.dll"}])
    event = usage.startup_failed("/x", "1.9.28", 42)   # (split: not an e-mail address)
    assert event.startswith("startup-failed/1.9.28/access-violation@")
    assert event.endswith("Qt6Core.dll")
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [
        {"kind": "not-responding", "code": "", "module": ""}])
    assert usage.startup_failed("/x", "1.9.28", 42) == "startup-failed/1.9.28/not-responding"
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [])
    assert usage.startup_failed("/x", "1.9.28", 42) == "startup-failed/1.9.28"


def test_a_start_cut_short_by_the_pc_restarting_isnt_counted(monkeypatch):
    """The breadcrumb was left before Windows last started: the PC was shut down,
    restarted or lost power while the app loaded (a start with Windows, say). Not the
    app's problem, the same as an unclean exit's `pc-restarted`: nothing is counted."""
    from soundboard.core import exitwatch
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [])
    monkeypatch.setattr(exitwatch, "boot_time", lambda: 2000.0)
    assert usage.startup_failed("/x", "1.9.28", 42, started=1000.0) == ""
    # left after Windows started (or no date known): still counted
    assert usage.startup_failed("/x", "1.9.28", 42, started=3000.0) == "startup-failed/1.9.28"
    assert usage.startup_failed("/x", "1.9.28", 42) == "startup-failed/1.9.28"
    # a crash it left a trace of is still counted, restart or not
    assert usage.startup_failed("/x", "1.9.28", 42, _NATIVE, started=1000.0).startswith(
        "startup-failed/1.9.28/access-violation@")


def test_a_handled_problem_is_counted_once_with_our_line_never_the_message():
    """errors.warn / html show a problem the app caught; usage.warned counts it, once
    per run, as the error's type and the deepest line of our own code it came from."""
    try:
        exec(compile("def f():\n    raise KeyError('D:/private/secret.wav')\nf()",
                     "D:\\private\\code\\soundboard\\audio\\engine.py", "exec"), {})
    except KeyError as e:
        usage.warned(e)
        usage.warned(e)   # the same (type, place) again: once
    assert usage._pending == [f"warned/{__version__}/KeyError@soundboard/audio/engine.py:2"]
    assert "secret" not in usage._pending[0]
    # a problem whose traceback is all another library's: the type only
    try:
        exec(compile("raise ValueError('x')", "C:\\Python\\Lib\\json\\decoder.py", "exec"), {})
    except ValueError as e:
        usage.warned(e)
    assert usage._pending[-1] == f"warned/{__version__}/ValueError"
    usage.warned("an error string, no traceback")   # never counted
    assert len(usage._pending) == 2


def test_errors_counts_a_reportable_problem_but_not_the_pc_situation(monkeypatch):
    from soundboard.core import errors
    counted = []
    monkeypatch.setattr(usage, "warned", counted.append)
    errors.html(TypeError("boom in our code"))     # a bug: counted, offered a report
    assert [type(x).__name__ for x in counted] == ["TypeError"]
    errors.html(OSError(112, "no space"))          # the disk is full, not a bug
    assert len(counted) == 1


def test_a_noted_event_survives_a_failed_send_and_a_quit(sent, app_dir, monkeypatch):
    usage.note("unclean-exit/2.0.0")
    cfg = Config(stats_sent=1e18, stats_problems_seen=1.0)
    offline, real = [True], usage.send
    monkeypatch.setattr(usage, "send", lambda *a, **k: not offline[0] and real(*a, **k))
    usage.maybe_send(cfg)
    assert cfg.stats_pending == ["unclean-exit/2.0.0"]
    cfg.save()                                   # quit, start again
    cfg = Config.load()
    offline[0] = False
    usage.maybe_send(cfg)
    assert [h["path"] for h in _hits(sent[-1][0])] == ["unclean-exit/2.0.0"]
    assert cfg.stats_pending == []


def test_a_quit_before_any_send_keeps_noted_events(app_dir):
    usage.note("unclean-exit/2.0.0")
    cfg = Config()
    usage.remember(cfg)   # MainWindow._remember_usage, at quit
    assert cfg.stats_pending == ["unclean-exit/2.0.0"] and usage._pending == []
    for i in range(50):
        usage.note(f"unclean-exit/{i}.0")
    usage.remember(cfg)
    assert len(cfg.stats_pending) == usage.MAX_PENDING   # never grows without end


def test_the_first_start_of_a_new_version_says_it_was_updated(sent):
    cfg = Config(stats_sent=1e18, stats_problems_seen=1.0)
    usage.started(cfg)                     # never noted a version: not an update
    assert cfg.stats_version == __version__ and cfg.stats_pending == []
    usage.started(cfg)                     # the same version again
    assert cfg.stats_pending == []
    cfg.stats_version = "1.0.0"
    usage.started(cfg)
    usage.maybe_send(cfg)
    assert [h["path"] for h in _hits(sent[0][0])] == [f"updated/1.0.0-to-{__version__}"]
    cfg.stats_version = "not a version!"   # never sent as it is
    usage.started(cfg)
    assert cfg.stats_pending == []


def test_launches_are_counted_only_while_the_count_is_on(sent):
    cfg = Config()
    net.configure_features(off=["usage_stats"])
    usage.started(cfg)
    assert cfg.stats_launches == 0 and cfg.stats_version == __version__
    net.configure_features()
    for _ in range(3):
        usage.started(cfg)
    usage.maybe_send(cfg)
    assert "launches/2-5" in _paths(sent[0][0])
    assert cfg.stats_launches == 0         # counted: starts again
    cfg.stats_sent -= usage.EVERY_S        # left open all day: 0
    usage.maybe_send(cfg)
    assert "launches/0" in _paths(sent[1][0])


def test_downloads_say_the_site_and_how_many_never_the_link(sent):
    cfg = Config()
    net.configure_features(off=["usage_stats"])   # off: nothing piles up for later
    usage.downloaded(cfg, "https://www.tiktok.com/@me/video/1", "link", "add", True)
    assert cfg.stats_downloads == 0
    net.configure_features()
    usage.downloaded(cfg, "https://youtu.be/abc?si=secret", "search", "add", True)
    usage.downloaded(cfg, "https://music.youtube.com/watch?v=x", "search", "play", True)
    usage.downloaded(cfg, "https://example.org/my-file.mp3", "link", "add", False, "403")
    usage.downloaded(cfg, "https://youtu.be/b", "link", "add", False, "a made-up why")
    usage.maybe_send(cfg)
    paths = _paths(sent[0][0])
    assert "downloads/2-5" in paths
    # the TikTok link went while it was off: never sent later
    assert "used/dl-tiktok" not in paths and "used/dl-link" not in paths
    for k in ("dl-youtube", "dl-search", "dl-add", "dl-play",
              "dl-failed-other", "dl-failed-youtube", "dl-failed-why-403",
              "dl-failed-why-other"):
        assert f"used/{k}" in paths
    assert "used/dl-other" not in paths   # it failed: only dl-failed-other
    body = sent[0][0].data.decode("utf-8")
    assert "secret" not in body and "example.org" not in body and "my-file" not in body
    assert cfg.stats_downloads == 0       # counted: starts again
    cfg.stats_sent -= usage.EVERY_S
    usage.maybe_send(cfg)
    assert "downloads/0" in _paths(sent[1][0])


@pytest.mark.parametrize("url, site", [
    ("https://www.youtube.com/shorts/x", "youtube"), ("https://m.youtube.com/watch", "youtube"),
    ("https://vm.tiktok.com/abc", "tiktok"), ("https://soundcloud.com/a/b", "soundcloud"),
    ("https://twitter.com/a/status/1", "x"), ("https://x.com/a/status/1", "x"),
    ("https://old.reddit.com/r/a", "reddit"), ("https://www.myinstants.com/x", "myinstants"),
    ("https://notyoutube.com/x", "other"), ("not a link", "other"),
])
def test_download_sites_are_from_a_fixed_list(url, site):
    assert usage.download_site(url) == site
    assert f"dl-{site}" in usage.FEATURES and f"dl-failed-{site}" in usage.FEATURES


@pytest.mark.parametrize("n, b", [(0, "0"), (1, "1"), (5, "2-5"), (6, "6-20"), (21, "21-plus")])
def test_downloads_are_a_rough_bucket(n, b):
    assert usage.download_bucket(n) == b


@pytest.mark.parametrize("n, b", [(0, "0"), (1, "1"), (2, "2-5"), (5, "2-5"), (6, "6-plus")])
def test_launches_are_a_rough_bucket(n, b):
    assert usage.launch_bucket(n) == b


@pytest.mark.parametrize("platform, ver, tag", [
    ("win32", (10, 22631), "win11"), ("win32", (10, 19045), "win10"),
    ("win32", (6, 9600), "win-older"), ("linux", None, "linux"), ("darwin", None, "other")])
def test_the_system_is_only_a_rough_name(monkeypatch, platform, ver, tag):
    monkeypatch.setattr(usage.sys, "platform", platform)
    if ver:
        monkeypatch.setattr(usage.sys, "getwindowsversion",
                            lambda: SimpleNamespace(major=ver[0], build=ver[1]), raising=False)
    assert usage.os_tag() == tag


def test_problems_follow_the_switch(sent, app_dir):
    cfg = Config(stats_sent=1e18, stats_problems_seen=1.0)
    _report(app_dir, "crash-a.txt", "Onion Board crash report\nVersion:  2.0.0\n", 2000)
    usage.note("unclean-exit/2.0.0")
    net.configure_features(off=["usage_stats"])
    usage.maybe_send(cfg, app_dir=app_dir)
    assert sent == []


def test_uninstall_count_command_line(sent, app_dir, monkeypatch):
    cfg = Config()
    cfg.stats_id = "a" * 32
    cfg.save()
    assert app.uninstall_count() == 0
    assert [h["path"] for h in _hits(sent[0][0])] == [f"uninstall/{__version__}"]
    assert _hits(sent[0][0])[0]["session"] == "a" * 32


def test_uninstall_count_sends_nothing_when_switched_off_or_never_counted(sent, app_dir):
    assert app.uninstall_count() == 0   # no config: never counted
    cfg = Config()
    cfg.stats_id = "a" * 32
    cfg.net_off = ["usage_stats"]
    cfg.save()
    assert app.uninstall_count() == 0
    cfg.net_off, cfg.net_offline = [], True
    cfg.save()
    assert app.uninstall_count() == 0
    assert sent == []


def test_uninstall_count_never_fails_the_uninstall(sent, app_dir, monkeypatch):
    cfg = Config()
    cfg.stats_id = "a" * 32
    cfg.save()
    monkeypatch.setattr(usage, "send", lambda p: 1 / 0)
    assert app.uninstall_count() == 0


# ---- how it's used: buckets and fixed names only ----------------------------------

def _sound(i: int, plays: int = 0, hotkey: str = "") -> library.SoundMeta:
    return library.SoundMeta(id=f"s{i}", name=f"Secret name {i}", file=f"C:/x/{i}.wav",
                             plays=plays, hotkey=hotkey)


def _paths(req) -> list[str]:
    return [h["path"] for h in _hits(req, about=True)]


def test_the_daily_count_says_roughly_how_its_used(sent):
    cfg = Config(route="mic", language="de", sounds=[_sound(i, plays=2) for i in range(12)])
    cfg.sounds[0].hotkey = "ctrl+f1"
    usage.used("voice-changer")
    usage.used("not-a-feature")   # never sent: only FEATURES
    usage.maybe_send(cfg)
    paths = _paths(sent[0][0])
    # 24 plays already: not a new install, so it's aged from its folder
    assert [p for p in paths if p.startswith(("route/", "sounds/", "played/", "lang/"))] == [
        "route/mic", "sounds/11-50", "played/0", f"lang/{i18n.current()}/picked"]
    assert {p for p in paths if p.startswith("used/")} == {"used/voice-changer", "used/hotkeys"}
    assert sum(p.startswith("age/") for p in paths) == 1
    body = sent[0][0].data.decode("utf-8")
    assert "Secret name" not in body and "ctrl+f1" not in body and "x/0.wav" not in body
    # the plays and features since then, a day later
    cfg.sounds[1].plays += 5
    cfg.stats_sent -= usage.EVERY_S
    usage.maybe_send(cfg)
    paths = _paths(sent[1][0])
    assert "played/1-10" in paths and "used/voice-changer" not in paths
    assert "used/hotkeys" in paths   # still set up


@pytest.mark.parametrize("n, b", [(0, "0"), (1, "1-10"), (10, "1-10"), (11, "11-50"),
                                  (50, "11-50"), (51, "51-plus"), (-3, "0")])
def test_counts_are_rough_buckets(n, b):
    assert usage.bucket(n) == b


@pytest.mark.parametrize("days, b", [(0, "day-1"), (0.9, "day-1"), (1, "days-2-7"),
                                     (6.9, "days-2-7"), (7, "days-8-30"),
                                     (30, "days-31-plus"), (400, "days-31-plus")])
def test_age_is_a_rough_bucket(days, b):
    assert usage.age_bucket(days) == b


def test_an_odd_language_or_route_isnt_sent_as_typed(sent):
    cfg = Config(route="somewhere-new", language="<script>")
    usage.maybe_send(cfg)
    paths = _paths(sent[0][0])
    assert f"lang/{i18n.current()}/picked" in paths
    assert not any(p.startswith("route/") for p in paths)
    assert "<script>" not in sent[0][0].data.decode("utf-8")


def test_the_daily_count_says_the_language_showing_and_windows_own(sent, monkeypatch):
    monkeypatch.setattr(i18n, "windows_language", lambda: "de-AT")
    i18n.in_language("de", lambda: usage.maybe_send(Config(language="de")))
    paths = _paths(sent[0][0])
    assert "lang/de/picked" in paths and "lang-windows/de" in paths
    # none picked: English, as the board doesn't follow Windows by itself yet
    assert usage.lang_tags(Config()) == ["lang/en/default", "lang-windows/de"]
    monkeypatch.setattr(i18n, "FOLLOW_WINDOWS", True)
    assert i18n.in_language("pt-BR", lambda: usage.lang_tags(Config()))[0] == (
        "lang/pt-BR/windows")
    # a Windows language the app doesn't come in, or a full locale: a shipped code only
    monkeypatch.setattr(i18n, "windows_language", lambda: "en-NZ")
    assert usage.lang_tags(Config())[1] == "lang-windows/en"
    monkeypatch.setattr(i18n, "windows_language", lambda: "kl-GL")
    assert usage.lang_tags(Config())[1] == "lang-windows/en"


def test_the_language_isnt_sent_with_the_count_off(sent, monkeypatch):
    monkeypatch.setenv("ONIONBOARD_NO_STATS", "1")
    usage.maybe_send(Config(language="de"))
    assert not sent


def test_a_new_install_sends_its_first_steps_once_each(sent):
    cfg = Config()
    usage.step(cfg, "added-sound")
    usage.step(cfg, "added-sound")
    usage.step(cfg, "played-sound")
    usage.step(cfg, "not-a-step")
    assert [p for (req, _f) in sent for p in _paths(req)] == [
        "step/added-sound", "step/played-sound"]
    usage.maybe_send(cfg)   # its first daily count: a day-old install
    assert "age/day-1" in _paths(sent[-1][0])


def test_adding_a_tab_is_sent_at_once_not_a_day_later(sent):
    """+ More tabs is used minutes in, after the first daily count went: waiting for
    the next one lost it for everyone who only tried the app once."""
    cfg = Config(stats_sent=1.0, stats_started=1.0, stats_steps=["added-sound"])
    usage.step(cfg, "added-radio-tab")
    usage.step(cfg, "added-radio-tab")
    usage.step(cfg, "added-voice-tab")   # every user starts with it: not a step
    assert [p for (req, _f) in sent for p in _paths(req)] == ["step/added-radio-tab"]


def test_a_copy_counted_before_never_sends_first_steps(sent):
    cfg = Config(stats_sent=1.0)
    usage.step(cfg, "played-sound")
    assert sent == [] and set(cfg.stats_steps) == set(usage.STEPS) and cfg.stats_started


def test_first_steps_obey_the_switch(sent):
    net.configure_features(off=[usage.FEATURE])
    cfg = Config()
    usage.step(cfg, "played-sound")
    assert sent == [] and cfg.stats_steps == []


def test_the_triggers_tab_counts_its_features(sent):
    """The Onion Watch add-on passes its feature names through BoardHost.count: sent as
    used/triggers-<name>, anything else dropped."""
    from soundboard.ui.triggers.triggershost import BoardHost
    host = BoardHost.__new__(BoardHost)    # count() needs nothing of the window
    host.count("mode-colour")
    host.count("pack-import")
    host.count("D:/pics/secret.png")
    usage.maybe_send(Config())
    used = {p for p in _paths(sent[0][0]) if p.startswith("used/")}
    assert used == {"used/triggers-mode-colour", "used/triggers-pack-import"}


def test_features_used_survive_a_quit(app_dir):
    cfg = Config()
    usage._used.clear()
    usage.used("youtube")
    usage.remember(cfg)
    cfg.save()
    assert Config.load().stats_used == ["youtube"]


# ---- at a quit: what waits for the next count goes then ------------------------------

def test_a_quit_sends_what_waits_for_the_next_count(sent, app_dir):
    """Someone who never starts it again: their last day's features, tabs and
    one-off events still arrive. Never the daily count or its buckets."""
    cfg = Config(stats_sent=1e18, stats_problems_seen=1.0, stats_tabs=["radio"],
                 stats_pending=["updated/2.0.0-to-2.0.1"])
    usage.used("youtube")
    usage.note("warned/2.0.1/KeyError")
    finish = usage.at_quit(cfg, app_dir=app_dir)
    assert finish() is True
    hits = json.loads(sent[0][0].data.decode("utf-8"))["hits"]
    assert [h["path"] for h in hits] == ["used/youtube", "tab/radio",
                                         "updated/2.0.0-to-2.0.1", "warned/2.0.1/KeyError"]
    assert all(h["event"] and h["ref"] == usage.user_tag(cfg.stats_id) for h in hits)
    assert sent[0][1] == "usage_stats"
    assert cfg.stats_used == [] and cfg.stats_tabs == [] and cfg.stats_pending == []
    assert cfg.stats_sent == 1e18                  # the daily count is still its own


def test_a_quit_with_nothing_waiting_sends_nothing(sent, app_dir):
    cfg = Config(stats_sent=1e18, stats_problems_seen=1.0, route="mic")
    assert usage.at_quit(cfg, app_dir=app_dir) is None
    assert sent == []


@pytest.mark.parametrize("why", ["off", "source"])
def test_a_quit_follows_the_switch(sent, app_dir, monkeypatch, why):
    cfg = Config(stats_sent=1e18, stats_tabs=["radio"])
    if why == "off":
        net.configure_features(off=["usage_stats"])
    else:
        monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert usage.at_quit(cfg, app_dir=app_dir) is None
    assert sent == [] and cfg.stats_tabs == ["radio"]


def test_a_quit_that_cant_send_keeps_it_all_for_the_next_count(sent, app_dir, monkeypatch):
    monkeypatch.setattr(usage, "send", lambda *a, **k: False)
    cfg = Config(stats_sent=1e18, stats_problems_seen=1.0, stats_tabs=["radio"],
                 stats_used=["youtube"], stats_pending=["unclean-exit/2.0.0"])
    assert usage.at_quit(cfg, app_dir=app_dir)() is False
    assert cfg.stats_tabs == ["radio"] and cfg.stats_used == ["youtube"]
    assert cfg.stats_pending == ["unclean-exit/2.0.0"]


def test_a_slow_quit_send_is_waited_for_only_briefly(sent, app_dir, monkeypatch):
    import threading
    import time
    gate = threading.Event()
    monkeypatch.setattr(usage, "threading", threading)
    monkeypatch.setattr(usage, "QUIT_WAIT_S", 0.2)
    monkeypatch.setattr(usage, "send", lambda *a, **k: gate.wait(5))
    cfg = Config(stats_sent=1e18, stats_tabs=["radio"])
    t0 = time.monotonic()
    assert usage.at_quit(cfg, app_dir=app_dir)() is False
    assert time.monotonic() - t0 < 2
    assert cfg.stats_tabs == ["radio"]
    gate.set()


def test_closing_the_window_sends_what_waits_and_saves(window, sent):  # noqa: F811
    window.cfg.stats_sent = 1e18
    window.cfg.stats_tabs = ["radio"]
    window.shutdown()
    assert [p for r, _ in sent for p in _paths(r)] == ["tab/radio"]
    assert Config.load().stats_tabs == []


def test_a_slow_quit_is_out_of_sight_and_no_freeze(window, sent, qapp):  # noqa: F811
    # 2.3.1: a quit taking over 5 s, the window still showing, came in as a freeze
    # stuck in the quit count's wait
    from soundboard.core.hangwatch import HangWatch
    window.show()
    qapp.hangwatch = HangWatch(hang_s=60)
    try:
        window.shutdown()
        assert not window.isVisible()
        assert qapp.hangwatch._stop.is_set()
    finally:
        qapp.hangwatch.stop()
        del qapp.hangwatch


def test_what_comes_in_during_a_quit_send_stays(sent, app_dir):
    cfg = Config(stats_sent=1e18, stats_problems_seen=1.0, stats_pending=["a/1"])
    finish = usage.at_quit(cfg, app_dir=app_dir)
    cfg.stats_pending = [*cfg.stats_pending, "b/1"]
    cfg.stats_tabs = ["apps"]
    assert finish() is True
    assert cfg.stats_pending == ["b/1"] and cfg.stats_tabs == ["apps"]



# ---- how long it was open ------------------------------------------------------------

def test_open_time_adds_up_ticks_and_skips_sleep(sent):
    cfg = Config()
    usage.open_tick(cfg, now=1000)        # the start: nothing yet
    usage.open_tick(cfg, now=1300)        # 5 min
    usage.open_tick(cfg, now=1600)        # 5 min
    usage.open_tick(cfg, now=1600 + 3600)   # an hour's gap: the PC slept, not counted
    usage.open_tick(cfg, now=5200 + 300)  # 5 min
    assert cfg.stats_open_s == 900


def test_open_time_doesnt_pile_up_while_the_count_is_off(sent):
    cfg = Config(net_off=["usage_stats"])
    net.configure_features(cfg.net_off)
    usage.open_tick(cfg, now=0)
    usage.open_tick(cfg, now=300)
    assert cfg.stats_open_s == 0


def test_the_daily_count_says_roughly_how_long_it_was_open(sent):
    cfg = Config(stats_open_s=2 * 3600)
    usage.maybe_send(cfg)
    paths = [p for p in _paths(sent[0][0]) if p.startswith("open/")]
    assert paths == ["open/1-3h"]
    assert cfg.stats_open_s < 60    # counted: starts again from about nothing


@pytest.mark.parametrize("seconds, b", [(0, "under-15m"), (899, "under-15m"),
                                        (900, "15m-1h"), (3600, "1-3h"),
                                        (3 * 3600, "3-8h"), (8 * 3600, "8h-plus")])
def test_open_time_is_a_rough_bucket(seconds, b):
    assert usage.open_bucket(seconds) == b


def test_settings_that_are_set_count_every_day(monkeypatch):
    from soundboard.online import quality
    monkeypatch.setattr(quality, "current", quality.Prefs(keep_source=False))
    cfg = Config(sidebar_open=False, apps_categories=["Games", "Other", "Stream stuff"])
    assert {"source-off", "rail-shut", "apps-own-categories"} <= set(usage.features_now(cfg))
    monkeypatch.setattr(quality, "current", quality.Prefs())
    cfg = Config(sidebar_open=True, apps_categories=["Browsers", "Games", "Other"])
    assert not {"source-off", "rail-shut", "apps-own-categories"} & set(usage.features_now(cfg))
    assert set(usage.features_now(cfg)) <= set(usage.FEATURES)


def test_apps_built_in_categories_match_the_apps_tab():
    from soundboard.ui.apps.appspanel import APP_CATEGORIES
    assert set(usage.APPS_BUILT_IN) == {*APP_CATEGORIES, "Other"}


def test_every_name_the_app_counts_is_in_features():
    """A usage.used("x") anywhere in the app whose name isn't in FEATURES is silently
    dropped: catch the typo here."""
    import re
    from pathlib import Path
    import soundboard
    root = Path(soundboard.__file__).parent
    names = set()
    for f in root.rglob("*.py"):
        names |= set(re.findall(r'usage\.used\("([a-z0-9-]+)"', f.read_text(encoding="utf-8")))
    assert names and not names - set(usage.FEATURES)
    for k in ("normal", "streamer", "games", "all"):   # setupwizard.uses() keys
        assert f"use-{k}" in usage.FEATURES


def test_the_daily_count_goes_by_the_calendar_day():
    """8 pm, then 6 pm the next day: both days count (22 hours isn't a whole day)."""
    import time as _t
    eight_pm = _t.mktime((2026, 10, 12, 20, 0, 0, 0, 0, -1))
    assert usage.due(eight_pm, eight_pm + 22 * 3600)
    assert not usage.due(eight_pm, eight_pm + 60)            # the same evening
    assert usage.due(eight_pm, eight_pm + usage.EVERY_S)    # a whole day
    assert not usage.due(1e18, eight_pm)                     # the clock went back


def test_every_name_in_a_used_call_is_in_features():
    """usage.used("a" if x else "b"): every quoted name in the call, not only the first,
    and the f-string families' keys."""
    import re
    from pathlib import Path
    import soundboard
    root = Path(soundboard.__file__).parent
    names = set()
    for f in root.rglob("*.py"):
        for call in re.findall(r'usage\.used\(((?:[^()]|\([^()]*\))*)\)',
                               f.read_text(encoding="utf-8")):
            # the names: the first argument, and each `else "…"` of a choice
            names |= set(re.findall(r'(?:^|\(|else)\s*"([a-z0-9-]+)"', call.strip()))
    assert {"mic-effect-said-no", "on-air-off", "get-ffmpeg-auto-failed"} <= names
    assert not names - set(usage.FEATURES)
    for k in usage.VOICE_TABS:
        assert f"voice-tab-{k}" in usage.FEATURES
    for k in usage.RECOVERY:
        assert f"recovery-{k}" in usage.FEATURES
    for k in (*usage.MIC_FAILS, *usage.RECOVERY_FAILS):
        assert f"recovery-failed-{k}" in usage.FEATURES
    for k in usage.MIC_FAILS:
        assert f"mic-effect-failed-{k}" in usage.FEATURES
        assert f"mic-effect-fix-failed-{k}" in usage.FEATURES


def test_mic_effect_failure_words_match_directmic():
    from soundboard.mic import directmic
    assert usage.MIC_FAILS == directmic.FAIL_KINDS
    # a translated message is never matched: plain text is "code-other"
    assert directmic.fail_kind(directmic.unfinished()) == "code-other"


def test_voice_tabs_and_recovery_actions_match_the_ui():
    import re
    from pathlib import Path

    from soundboard.ui.setup import audiorecovery
    assert set(audiorecovery.INSTALLS) <= set(usage.RECOVERY)
    from soundboard.ui.voice import voicepanel
    src = Path(voicepanel.__file__).read_text(encoding="utf-8")
    assert set(re.findall(r'self\._section\("([a-z]+)"', src)) == set(usage.VOICE_TABS)


def test_network_background_and_helper_settings_count_every_day(monkeypatch):
    from soundboard.mic import michelper
    monkeypatch.setattr(michelper, "known", lambda same_dll=True: True)
    cfg = Config(net_mode="tor", net_offline=True, playing_background=True, route="mic")
    got = set(usage.features_now(cfg))
    assert {"net-tor", "net-offline", "playing-bg", "mic-helper"} <= got
    assert got <= set(usage.FEATURES)
    monkeypatch.setattr(michelper, "known", lambda same_dll=True: None)
    cfg = Config(net_mode="direct", route="cable")
    assert not {"net-proxy", "net-tor", "net-offline", "playing-bg", "mic-helper"} & set(
        usage.features_now(cfg))


def test_theme_is_a_built_in_name_or_other():
    assert usage.theme_tag("Dark") == "dark"
    assert usage.theme_tag("Cherry Blossom") == "cherry-blossom"
    assert usage.theme_tag("My secret theme") == "other"
    assert "theme/high-contrast" in usage.about(Config(theme="High Contrast"), 0.0)


def test_press_modes_count_every_day_and_match_the_library():
    """A pad set to Overlap (one at a time is the default since 2.0): counted every day."""
    assert set(usage.PRESS_MODES) == set(library.MODES) - {"restart"}
    snd = library.SoundMeta(id="a", name="A", file="a.wav", mode="overlap")
    got = set(usage.features_now(Config(sounds=[snd])))
    assert "press-overlap" in got and got <= set(usage.FEATURES)
    plain = library.SoundMeta(id="b", name="B", file="b.wav")
    assert not any(k.startswith("press-") for k in usage.features_now(Config(sounds=[plain])))


def test_views_hotkeys_leveler_and_sound_voices_count_every_day():
    """A tab shown as a list, hotkeys kept from the game, a voice key, auto push-to-talk,
    the leveler off and sounds with a voice: names only, every day they're set."""
    ai = library.SoundMeta(id="a", name="A", file="a.wav",
                           fx={"voice": {"name": "Robot", "ai": {"id": "x"}}})
    cfg = Config(pad_view="list", app_view="list", voice_view="list", hotkeys_share=False,
                 voice_hotkeys={"Robot": "F9"}, ptt_key="v", voice_level=False, sounds=[ai])
    got = set(usage.features_now(cfg))
    assert {"view-list-sounds", "view-list-apps", "view-list-voice", "hotkeys-share-off",
            "voice-hotkeys", "auto-ptt", "voice-leveler-off", "sound-voice",
            "sound-ai-voice"} <= got
    assert got <= set(usage.FEATURES)
    fx = library.SoundMeta(id="b", name="B", file="b.wav", fx={"voice": {"name": "Robot"}})
    got = set(usage.features_now(Config(sounds=[fx])))
    assert "sound-voice" in got and "sound-ai-voice" not in got
    plain = set(usage.features_now(Config(sounds=[library.SoundMeta(id="c", name="C",
                                                                     file="c.wav")])))
    assert not {k for k in plain if k.startswith(("view-list-", "sound-", "voice-", "auto-",
                                                  "hotkeys-share"))}


def test_bun_games_are_counted_by_a_fixed_name():
    from soundboard.ui.bun import bunpong
    assert set(bunpong.games()) <= set(usage.BUN_GAMES)
    assert usage.game_tag("whack") == "whack" and usage.game_tag("chess") == "other"
    assert all(f"egg-game-{g}" in usage.FEATURES for g in usage.BUN_GAMES)


def test_addon_installs_are_counted_by_a_fixed_name(monkeypatch):
    """An add-on's install, failure and Repair: its id from ADDONS, anything else "other"."""
    from pathlib import Path

    from soundboard.addons import modules
    import soundboard
    shipped = Path(soundboard.__file__).parent.parent / "modules"
    with_steps = {m.id for m in modules.discover([shipped]) if m.install_steps}
    assert with_steps and with_steps <= set(usage.ADDONS)
    seen = []
    monkeypatch.setattr(usage, "used", seen.append)
    for why, mid, broken in (("", "ai-voices", False), ("pip", "secret-addon", False),
                             ("", "live-voice", True)):
        monkeypatch.setattr(modules, "_install", lambda *a, why=why, **k: why)
        info = SimpleNamespace(id=mid, broken=broken, installed=not broken,
                               path=Path("nowhere"))
        assert modules.install(info, print) is (not why)
    assert seen == ["addon-installed-ai-voices", "addon-failed-other",
                    "addon-failed-other-pip", "addon-installed-live-voice", "addon-repaired"]
    assert set(seen) <= set(usage.FEATURES)


def test_getting_python_for_an_addon_is_counted(monkeypatch, tmp_path):
    from soundboard.online import pyget
    seen = []
    monkeypatch.setattr(usage, "used", seen.append)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(pyget, "pc_python", lambda: None)
    monkeypatch.setattr(pyget, "get", lambda d, on_line: "py.exe")
    assert pyget.for_module(tmp_path, print) == "py.exe"

    def fails(d, on_line):
        raise pyget.GetError("no")
    monkeypatch.setattr(pyget, "get", fails)
    with pytest.raises(pyget.GetError):
        pyget.for_module(tmp_path, print)
    assert seen == ["addon-got-python", "addon-python-failed"]


@pytest.mark.parametrize("failure", ["broken", "get-failed"])
def test_ffmpeg_failure_survives_a_send_and_restart_until_verified_recovery(sent, app_dir, failure):
    cfg = Config()
    usage.ffmpeg_state(cfg, failure)
    if failure == "get-failed":
        usage.used("get-ffmpeg-auto-failed")
    usage.maybe_send(cfg)
    failed_hits = _hits(sent[0][0], about=True)
    expected = "used/ffmpeg-broken" if failure == "broken" else "used/get-ffmpeg-auto-failed"
    assert expected in {h["path"] for h in failed_hits}
    assert cfg.stats_ffmpeg_failed and cfg.save()

    # The daily send cleared its flags, but not the unresolved-failure marker.
    cfg = Config.load()
    assert cfg.stats_ffmpeg_failed and not cfg.stats_used
    usage.ffmpeg_state(cfg, "missing")
    usage.ffmpeg_state(cfg, "unknown")
    assert cfg.stats_ffmpeg_failed
    cfg.stats_sent -= usage.EVERY_S
    usage.ffmpeg_state(cfg, "ok")
    usage.maybe_send(cfg)
    recovered_hits = _hits(sent[1][0], about=True)
    assert "used/ffmpeg-recovered" in {h["path"] for h in recovered_hits}
    assert {h["ref"] for h in failed_hits} == {h["ref"] for h in recovered_hits}
    assert not cfg.stats_ffmpeg_failed

    # A later healthy start isn't another recovery.
    usage.ffmpeg_state(cfg, "ok")
    usage.remember(cfg)
    assert not cfg.stats_used


def test_ffmpeg_check_that_only_timed_out_is_neither_broken_nor_recovered(sent):
    cfg = Config()
    usage.ffmpeg_state(cfg, "slow")
    usage.ffmpeg_state(cfg, "ok")
    usage.remember(cfg)
    assert not cfg.stats_ffmpeg_failed and not cfg.stats_used
    cfg = Config(stats_ffmpeg_failed=True)   # broken before: still waiting for proof
    usage.ffmpeg_state(cfg, "slow")
    assert cfg.stats_ffmpeg_failed
    usage.ffmpeg_state(cfg, "get-failed")    # the get it started failed: that counts
    assert cfg.stats_ffmpeg_failed


def test_ffmpeg_first_install_and_healthy_reinstall_arent_recoveries(sent):
    cfg = Config()
    usage.ffmpeg_state(cfg, "missing")
    usage.ffmpeg_state(cfg, "ok")
    usage.remember(cfg)
    assert not cfg.stats_ffmpeg_failed and not cfg.stats_used


@pytest.mark.parametrize("off", ["switch", "offline", "tor", "source"])
def test_ffmpeg_recovery_doesnt_track_while_the_count_is_off(sent, monkeypatch, off):
    cfg = Config(stats_ffmpeg_failed=True)
    if off == "switch":
        net.configure_features(off=[usage.FEATURE])
    elif off == "offline":
        net.configure_features(offline=True)
    elif off == "tor":
        monkeypatch.setattr(net, "_mode", net.TOR)
    else:
        monkeypatch.setattr(sys, "frozen", False)
    usage.ffmpeg_state(cfg, "broken")
    usage.ffmpeg_state(cfg, "ok")
    usage.remember(cfg)
    assert not cfg.stats_ffmpeg_failed and not cfg.stats_used


def test_packs_settings_pages_and_ytdlp_buttons_count_by_fixed_names():
    """Free packs by their built-in id (a newer one is "other"), Settings' pages by
    their key, yt-dlp's buttons by their job: every name is in FEATURES."""
    from soundboard.sounds import packs
    from soundboard.online import ytdl
    from soundboard.ui.settings import connection
    ids = {p.id for p in packs.built_in()}
    assert ids and ids <= set(usage.PACKS)
    assert {usage.pack_tag(i) for i in ids} == ids
    assert usage.pack_tag("someone-elses-pack") == "other"
    assert {f"pack-added-{k}" for k in usage.PACKS} <= set(usage.FEATURES)
    for job in (ytdl.update, ytdl.reset, ytdl.force_newest):
        assert connection.YTDLP_COUNTS[job.__name__] in usage.FEATURES
    assert {f"settings-page-{k}" for k in usage.SETTINGS_PAGES} <= set(usage.FEATURES)


def test_settings_pages_match_the_dialog():
    """A page added to Settings needs its name in SETTINGS_PAGES, or it's never counted."""
    import re
    from pathlib import Path
    from soundboard.ui.settings import settings
    src = Path(settings.__file__).read_text(encoding="utf-8")
    start = src.index("        pages = ((")
    block = src[start:src.index("        self.categories = QListWidget()", start)]
    keys = set(re.findall(r'\("([a-z]+)", _\(', block))
    assert keys == set(usage.SETTINGS_PAGES)


def test_background_hidden_categories_and_stream_api_count_every_day():
    """The voice changer's Background (and board sounds in it), a category hidden from
    All, and the control API's chat commands and alerts: names only, while they're set."""
    bg = {"enabled": True, "effects": {"backdrop": {"on": True, "rain": 0.6,
                                                    "sounds": [{"id": "x", "level": 0.5}]}}}
    cfg = Config(voice_fx=bg, hidden_from_all=["Memes"], api_enabled=True,
                 api_stream={"chat": {"tts": True}, "alerts": {"follow": [{"sound": "a"}]}})
    got = set(usage.features_now(cfg))
    assert {"voice-background", "voice-background-sounds", "hidden-from-all",
            "api-chat-rules", "api-alerts"} <= got
    assert got <= set(usage.FEATURES)
    off = {"enabled": True, "effects": {"backdrop": {"on": True, "rain": 0, "talk": 1}}}
    cfg = Config(voice_fx=off, api_enabled=False, api_stream=cfg.api_stream)
    assert not {k for k in usage.features_now(cfg)
                if k.startswith(("voice-background", "api-", "hidden-"))}


def test_stream_api_counts_a_chat_command_and_an_alert_by_name(monkeypatch):
    from soundboard.control import streamapi
    monkeypatch.setattr(usage, "_used", set())
    mw = type("Window", (), {})()   # anything a weak reference can point at
    streamapi._log(mw, "chat", user="someone", command="tts", text="hi")
    streamapi._log(mw, "alert", type="donation", user="someone", amount=5.0)
    streamapi._log(mw, "alert", type="follow", user="someone", amount=None)
    assert usage._used == {"api-chat-command", "api-alert-donation", "api-alert"}


def test_a_freeze_on_a_pc_short_of_memory_says_so(tmp_path):
    """hangwatch notes how full the PC's memory was and how fast the app page-faulted:
    the count says `mem-90` / `paging` (a PC swapping, not a bug), nothing below that."""
    f = tmp_path / "crash-x.txt"
    _freeze(f, "12 s", 0, "", inner="\nPC memory in use: 96%\nPage faults: 5400/s\n")
    assert usage._report_event(f).endswith("/lasted-10-30s/idle/mem-90/paging")
    _freeze(f, "12 s", 0, "", inner="\nPC memory in use: 84%\nPage faults: 40/s\n")
    assert usage._report_event(f).endswith("/lasted-10-30s/idle/mem-80")
    _freeze(f, "12 s", 0, "", inner="\nPC memory in use: 55%\nPage faults: 40/s\n")
    assert usage._report_event(f).endswith("/lasted-10-30s/idle")


def test_a_rare_loading_screen_is_counted_by_its_tier(monkeypatch):
    """Golden, Ice, Galaxy and Rainbow Bun: each has its name in FEATURES (one per key of
    splashacts.RARES), and a launch that showed one notes it; a plain one notes none."""
    from soundboard.ui.bun import splash, splashacts
    assert tuple(splashacts.RARES) == ("rainbow", "galaxy", "ice", "gold")
    assert set(usage.SPLASH_RARES) == set(splashacts.RARES)
    assert {f"splash-{k}" for k in usage.SPLASH_RARES} <= set(usage.FEATURES)
    monkeypatch.setattr(splash, "_show", splashacts.Show(rare="ice"))
    assert splash.rare() == "ice"
    monkeypatch.setattr(splash, "_show", splashacts.Show())
    assert splash.rare() is None


def test_plain_themes_count_as_textures_off():
    """Textured is the default: only a board set to Plain sends `textures-off`."""
    assert "textures-off" not in usage.features_now(Config())
    assert "textures-off" in usage.features_now(Config(theme_texture=False))


def test_an_earned_achievement_is_counted_by_its_id_only(sent):
    usage.achieved("first_blood")
    usage.achieved("made_up_by_a_newer_version")
    assert usage._used == {"ach-first-blood"}
    from soundboard.core import achievements
    assert {usage.ach_tag(a.id) for a in achievements.ALL} <= set(usage.FEATURES)


def test_the_daily_count_says_roughly_how_many_achievements(sent):
    cfg = Config()
    assert "achievements/0" in usage.about(cfg, 1e9)
    cfg.achievements = {"got": {"first_blood": 1, "critic": 2, "regular": 3}}
    assert "achievements/3-5" in usage.about(cfg, 1e9)
    assert [usage.ach_bucket(n) for n in (1, 2, 6, 11, 21, 56)] == [
        "1-2", "1-2", "6-10", "11-20", "21-plus", "21-plus"]


def test_the_daily_count_says_roughly_the_achievement_score(sent):
    cfg = Config()
    assert "ach-score/0" in usage.about(cfg, 1e9)
    # common 10 + common 10 + uncommon 25, and an id from a newer version adds nothing
    cfg.achievements = {"got": {"first_blood": 1, "critic": 2, "regular": 3, "new_one": 4}}
    assert "ach-score/1-50" in usage.about(cfg, 1e9)
    assert [usage.score_bucket(n) for n in (51, 150, 151, 401, 1001, 2001, 3010)] == [
        "51-150", "51-150", "151-400", "401-1000", "1001-2000", "2001-plus", "2001-plus"]


def test_lite_twitch_and_achievement_pop_ups_count_every_day():
    cfg = Config(lite_mode=True, light_voice="off", twitch_token="t",
                 achievement_popups=True, achievement_sound=True)
    now = set(usage.features_now(cfg))
    assert {"lite-mode", "light-voice-off", "twitch-connected", "achievement-popups",
            "achievement-chime"} <= now <= set(usage.FEATURES)
    assert not {"lite-mode", "light-voice-on", "light-voice-off", "twitch-connected",
                "achievement-popups", "achievement-chime"} & set(usage.features_now(Config()))


def test_the_twitch_channel_only_when_ticked_and_connected(sent):
    cfg = Config(twitch_token="t", twitch_login="some_streamer")
    usage.maybe_send(cfg)   # connected, box not ticked: never the name
    assert not any("twitch-channel" in h["path"] for h in _hits(sent[-1][0], about=True))
    cfg.twitch_share = True
    cfg.stats_sent -= usage.EVERY_S
    usage.maybe_send(cfg)
    assert "twitch-channel/some_streamer" in [h["path"] for h in _hits(sent[-1][0])]
    cfg.twitch_token = ""   # disconnected: nothing, ticked or not
    cfg.stats_sent -= usage.EVERY_S
    usage.maybe_send(cfg)
    assert not any("twitch-channel" in h["path"] for h in _hits(sent[-1][0], about=True))
    cfg.twitch_token, cfg.twitch_login = "t", "../me@example.com"   # never a stray login
    cfg.stats_sent -= usage.EVERY_S
    usage.maybe_send(cfg)
    assert not any("twitch-channel" in h["path"] for h in _hits(sent[-1][0], about=True))


def test_a_long_send_goes_in_parts_goatcounter_takes(sent):
    hits = [{"path": f"used/x{i}", "event": True} for i in range(usage.MAX_HITS * 2 + 5)]
    assert usage.send(hits)
    parts = [json.loads(req.data)["hits"] for req, _f in sent]
    assert [len(p) for p in parts] == [usage.MAX_HITS, usage.MAX_HITS, 5]
    assert [h for p in parts for h in p] == hits


@pytest.mark.parametrize("kind", usage.MIC_TESTS)
def test_the_setup_guides_mic_test_is_one_fixed_name(sent, kind):
    """How the guide's mic test went: `used/mic-test-<kind>` and nothing about the mic,
    once a day however often it's tried (the network is blocked: `sent` records it)."""
    cfg = Config(mic_device="Headset Mic (Secret Brand)")
    usage.used(f"mic-test-{kind}")
    usage.used(f"mic-test-{kind}")
    usage.maybe_send(cfg)
    paths = _paths(sent[0][0])
    assert paths.count(f"used/mic-test-{kind}") == 1
    assert "Secret" not in sent[0][0].data.decode("utf-8")
    cfg.stats_sent -= usage.EVERY_S
    usage.maybe_send(cfg)   # the next day: not again unless it happened again
    assert f"used/mic-test-{kind}" not in _paths(sent[1][0])


@pytest.mark.parametrize("why", ["switched off", "source", "dev pc"])
def test_the_mic_test_count_obeys_the_switch(sent, monkeypatch, why):
    if why == "switched off":
        net.configure_features(["usage_stats"])
    elif why == "source":
        monkeypatch.delattr(sys, "frozen")
    else:
        monkeypatch.setenv("ONIONBOARD_NO_STATS", "1")
    cfg = Config()
    usage.used("mic-test-blocked")
    usage.maybe_send(cfg)
    assert usage.at_quit(cfg) is None
    assert sent == [] and cfg.stats_used == []


# -- failed(): what a vague failure count can add ----------------------------------------

def test_a_vague_failure_says_its_type_place_and_number_never_its_words():
    """dl-failed-why-other told nothing: failed() adds the error's type, our own line and
    the number it carried, never the message (a title, a path, a link)."""
    try:
        exec(compile("def f():\n    raise OSError(22, 'D:/private/secret.mp3')\nf()",
                     "D:\\private\\soundboard\\online\\ytfetch.py", "exec"), {})
    except OSError as e:
        usage.failed("dl-other", *usage.error_detail(e))
        usage.failed("dl-other", *usage.error_detail(e))   # the same again: once
    assert usage._pending == [f"failed/{__version__}/dl-other/"
                              "OSError@soundboard/online/ytfetch.py:2/errno-22"]
    assert "secret" not in usage._pending[0] and "private" not in usage._pending[0]


def test_error_detail_reads_the_numbers_an_error_carries():
    import urllib.error
    err = urllib.error.HTTPError("https://example.com/x", 410, "Gone", {}, None)
    assert usage.error_detail(err) == ["HTTPError", "http-410"]
    win = OSError(0, "x")
    win.winerror = 10013   # (what Windows sets)
    assert usage.error_detail(win)[1:] == ["err-10013"]
    from soundboard.online.ytsites import FetchError
    fetch = FetchError("The site refused it.")
    fetch.kind, fetch.raw = "ExtractorError", "ERROR: [youtube] x: HTTP Error 403: Forbidden"
    assert usage.error_detail(fetch) == ["ExtractorError", "http-403"]
    assert usage.error_detail(RuntimeError("[WinError 1450] odd")) == ["RuntimeError",
                                                                      "err-1450"]
    assert usage.error_detail(None) == []


@pytest.mark.parametrize("text, word", [
    ("Read timed out. (read timeout=20)", "read"),
    ("<urlopen error _ssl.c:983: The handshake operation timed out>", "handshake"),
    ("Connection to www.youtube.com timed out. (connect timeout=20)", "connect"),
    ("The connection timed out. Check your internet and try again.", "connect"),
    ("timed out", "other")])
def test_timeout_kind_says_which_wait_ran_out(text, word):
    assert usage.timeout_kind(Exception(text)) == word


def test_a_search_timeout_says_if_it_was_our_own_helper():
    from soundboard.online.ytsites import FetchError
    e = FetchError("The site took too long to answer. Try again.")
    e.kind = "helper-timeout"
    assert usage.failure_detail("timeout", e) == ["helper"]
    assert usage.failure_detail("private", e) == []   # its word says it already


def test_failed_sends_only_known_counts_and_safe_parts():
    usage.failed("not-a-count", "x")
    usage.failed("addon-other", "")   # nothing known: nothing sent
    usage.failed("addon-other", "live-voice", "has space", "https://example.com",
                 "D:/private/me", "KeyError@C:/Python/Lib/json.py:3", "http-500")
    assert usage._pending == [f"failed/{__version__}/addon-other/live-voice/http-500"]
    assert set(usage.FAILED) >= {"dl-other", "search-other", "search-timeout",
                                 "ffmpeg-broken", "ffmpeg-get", "mic-code-1", "mic-code",
                                 "addon-other"}


def test_a_broken_ffmpeg_is_counted_with_why(sent):
    cfg = Config()
    usage.ffmpeg_state(cfg, "broken", "err-193")
    assert usage._pending == [f"failed/{__version__}/ffmpeg-broken/err-193"]
    assert "ffmpeg-broken" in usage._used and cfg.stats_ffmpeg_failed
