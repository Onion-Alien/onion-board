"""The anonymous usage count (soundboard/usage.py): on for new installs, off for
copies from before it existed, off when the installer's box is unticked, never sent
from source, without a key or while switched off, and it says only what SECURITY.md
says it does."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from soundboard import __version__, app, applog, library, net, reset, usage
from soundboard.library import Config


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


ABOUT = ("age/", "route/", "sounds/", "played/", "open/", "lang/", "used/")


def _hits(req, about=False) -> list[dict]:
    """The hits sent; without the daily picture of how it's used unless `about`."""
    hits = json.loads(req.data.decode("utf-8"))["hits"]
    return [h for h in hits if about or not h["path"].startswith(ABOUT)]


def test_a_new_install_counts_once_a_day(sent):
    cfg = Config()
    saved = []
    usage.maybe_send(cfg, lambda: saved.append(1))
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
    Config(net_off=["usage_stats", "radio"]).save()
    reset.reset([reset.SETTINGS])
    assert Config.load().net_off == ["usage_stats"]
    Config(net_off=["radio"]).save()
    reset.reset([reset.SETTINGS])
    assert Config.load().net_off == []


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
    from soundboard import updates

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
    yield
    usage._pending.clear()


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
    usage.maybe_send(cfg, lambda: saved.append(1), app_dir=app_dir)
    hits = _hits(sent[0][0])
    assert [h["path"] for h in hits] == ["crash/1.9.6", "error/1.9.6", "freeze/1.9.7"]
    assert "Bob" not in sent[0][0].data.decode()
    assert cfg.stats_problems_seen == 2002 and saved == [1]
    usage.maybe_send(cfg, app_dir=app_dir)   # nothing new: nothing sent
    assert len(sent) == 1


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
    src = "D:\\private\\code\\soundboard\\engine.py"
    f.write_text(_real_report(src) + "\n\nLast 60 log lines\n------\n"
                 '  File "C:\\soundboard\\ui\\other.py", line 7, in g\nOSError: x\n',
                 encoding="utf-8")
    assert usage._report_event(f) == "error/1.9.8/KeyError@soundboard/engine.py:2"
    # the freeze from a real 1.9.7 report: its deepest line of our own code
    f.write_text("Onion Board froze for 6 s\nVersion:  1.9.7\nTime:  x\n\n"
                 "What it was doing\n-----------------\n"
                 '  File "main.py", line 22, in <module>\n'
                 '  File "soundboard\\ui\\mainwindow.py", line 5898, in tick\n'
                 '  File "soundboard\\directmic.py", line 184, in make_ring\n'
                 '  File "pathlib\\_local.py", line 515, in stat\n', encoding="utf-8")
    assert usage._report_event(f) == ("freeze/1.9.7@soundboard/directmic.py:184"
                                      "<soundboard/ui/mainwindow.py:5898~_local.stat")


def test_a_freeze_says_where_the_window_was_never_another_thread(tmp_path):
    """hangwatch.py lists every other thread after the window's own stack; the
    place sent is the window's, and a thread start is blamed on its caller, not on
    threadnames.py's wrapper around Thread.start."""
    f = tmp_path / "freeze-x.txt"
    f.write_text("Onion Board froze for 6 s\nVersion:  1.9.20\nTime:  x\n\n"
                 "What it was doing\n-----------------\n"
                 '  File "main.py", line 22, in <module>\n'
                 '  File "soundboard\\ui\\mainwindow.py", line 5898, in tick\n'
                 '  File "soundboard\\threadnames.py", line 70, in named_start\n'
                 '  File "threading.py", line 999, in start\n'
                 "\nOther threads\n-------------\n"
                 'Thread "audio" (12):\n'
                 '  File "soundboard\\threadnames.py", line 68, in named_run\n'
                 '  File "soundboard\\engine.py", line 400, in _loop\n'
                 'Thread "x" (13):\n'
                 '  File "soundboard\\threadnames.py", line 70, in named_start\n',
                 encoding="utf-8")
    assert usage._report_event(f) == ("freeze/1.9.20@soundboard/ui/mainwindow.py:5898"
                                      "~threading.start")


def _freeze(f, lasted, window_cpu, others, inner='  File "threading.py", line 359, in wait\n'):
    f.write_text("Onion Board froze for 5 s\nVersion:  1.9.28\nTime:  x\n"
                 + (f"Lasted:   {lasted}\n" if lasted else "") + "\n"
                 "What it was doing\n-----------------\n"
                 '  File "D:\\private\\code\\soundboard\\ui\\mainwindow.py", line 50, in tick\n'
                 '  File "soundboard\\threadnames.py", line 70, in named_start\n'
                 '  File "soundboard\\voicesdk.py", line 80, in listen\n' + inner
                 + (f"\nWindow CPU: {window_cpu}%\n" if window_cpu is not None else "")
                 + "\nOther threads\n-------------\n" + others, encoding="utf-8")


def test_a_freeze_says_its_caller_what_it_waited_in_how_long_and_who_was_busy(tmp_path):
    """Enough to tell a freeze's cause from the count alone: the caller of the stuck
    line, the library call it was stuck in, how long it lasted, and whether the
    window was working itself, waiting on a busy thread, or everyone was waiting."""
    f = tmp_path / "crash-x.txt"
    hog = ('Thread "radio" (12), 95% CPU:\n'
           '  File "soundboard\\threadnames.py", line 68, in named_run\n'
           '  File "soundboard\\radio.py", line 400, in _decode\n'
           'Thread "calm" (13), 0% CPU:\n'
           '  File "soundboard\\engine.py", line 9, in _loop\n')
    _freeze(f, "42 s", 1, hog)
    assert usage._report_event(f) == (
        "freeze/1.9.28@soundboard/voicesdk.py:80<soundboard/ui/mainwindow.py:50"
        "~threading.wait/lasted-30s-2m/busy-thread@soundboard/radio.py:400")
    _freeze(f, "7 s", 100, hog)
    assert usage._report_event(f).endswith("/lasted-under-10s/busy-window")
    _freeze(f, "still frozen", 0, 'Thread "calm" (13), 2% CPU:\n'
            '  File "soundboard\\engine.py", line 9, in _loop\n')
    assert usage._report_event(f).endswith("~threading.wait/never-ended/idle")
    # stuck in our own line (time.sleep has no frame): no library part
    _freeze(f, "12 s", 0, "", inner="")
    assert usage._report_event(f) == ("freeze/1.9.28@soundboard/voicesdk.py:80"
                                      "<soundboard/ui/mainwindow.py:50/lasted-10-30s/idle")
    # an older report (no Lasted / CPU lines): only what it has
    _freeze(f, "", None, hog)
    assert usage._report_event(f) == ("freeze/1.9.28@soundboard/voicesdk.py:80"
                                      "<soundboard/ui/mainwindow.py:50~threading.wait")
    assert "private" not in usage._report_event(f)


def test_a_freeze_end_is_noted_without_counting_the_report_again(tmp_path, monkeypatch):
    import os
    from soundboard import applog
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    path = applog.save_freeze(5, '  File "soundboard\\engine.py", line 9, in f\n')
    assert usage._report_event(path).endswith("/never-ended")
    os.utime(path, (1_000_000, 1_000_000))
    applog.note_freeze_end(path, 23.4)
    assert path.stat().st_mtime == 1_000_000
    assert "Lasted:   23 s" in path.read_text(encoding="utf-8")
    assert usage._report_event(path).endswith("/lasted-10-30s")
    applog.note_freeze_end(path, 99)                       # once only
    assert "Lasted:   23 s" in path.read_text(encoding="utf-8")


def test_problem_events_keep_paths_outside_our_package_out(tmp_path):
    f = tmp_path / "crash-x.txt"
    # an odd install folder named soundboard: deeper than our package, so not sent
    f.write_text(_real_report("D:\\soundboard\\Python\\Lib\\json\\decoder.py"),
                 encoding="utf-8")
    assert usage._report_event(f) == "error/1.9.8/KeyError"
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
    assert len(_hits(sent[0][0])) == usage.MAX_PROBLEMS
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
    assert usage._pending == []


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
        "route/mic", "sounds/11-50", "played/0", "lang/de"]
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
    assert "lang/auto" in paths and not any(p.startswith("route/") for p in paths)


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
    from soundboard.ui.triggershost import BoardHost
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
