"""*Did you know?* tips: when one is due, which one, and the bar's Show me."""
from soundboard import tips
from soundboard.library import Config

from test_mainwindow import window  # noqa: F401  (the real MainWindow)


def cfg(**kw):
    return Config(setup_done=True, **kw)


def test_about_twenty_tips_each_with_a_known_place():
    from soundboard.ui.mainwindow import TAB_INDEX
    pages = {"privacy", "connection", "data", "general", "tabs", "appearance", "audio",
             "hotkeys", "overlay", "updates", "help", "remote", "about"}
    assert 18 <= len(tips.TIPS) <= 26 and len(tips.BY_KEY) == len(tips.TIPS)
    for t in tips.TIPS:
        kind, _, where = t.show.partition(":")
        assert (kind == "tab" and where in TAB_INDEX) or (kind == "settings" and where in pages) \
            or kind in ("search", "record", "deleted"), t.key
        assert len(t.text) < 160, t.key


def test_one_a_day_after_setup_never_twice_and_not_when_off():
    assert tips.due(Config(setup_done=False)) is None          # the guide first
    c = cfg()
    first = tips.due(c, day="2026-10-07")
    assert first is tips.TIPS[0]
    c.tips_seen.append(first.key)
    c.tip_day = "2026-10-07"
    assert tips.due(c, day="2026-10-07") is None               # once a day
    assert tips.due(c, day="2026-10-08") is tips.TIPS[1]       # the next one tomorrow
    c.tips_on = False
    assert tips.due(c, day="2026-10-08") is None
    c.tips_on, c.tips_seen = True, [t.key for t in tips.TIPS]
    assert tips.due(c, day="2026-10-09") is None               # all seen


def test_never_during_a_game_and_skips_switched_off_tabs():
    c = cfg(tips_seen=[t.key for t in tips.TIPS if t.key != "voice"])
    assert tips.due(c, game_up=lambda: True, day="x") is None
    assert tips.due(c, tab_on=lambda k: k != "voice", day="x") is None
    assert tips.due(c, day="x").key == "voice"


def test_tip_settings_survive_save_and_stay_out_of_backups(app_dir):
    from soundboard import backup
    Config(tips_on=False, tips_seen=["effects", "newer-tip"], tip_day="2026-10-07").save()
    c = Config.load()
    assert c.tips_on is False and c.tips_seen == ["effects", "newer-tip"]
    raw = backup.settings_of(c)
    assert "tips_seen" not in raw and "tip_day" not in raw and raw["tips_on"] is False


def test_window_shows_a_tip_and_show_me_goes_there(window, monkeypatch):  # noqa: F811
    w = window
    w.cfg.setup_done = True
    w.cfg.tips_seen = [t.key for t in tips.TIPS if t.key != "tabs"]
    w.cfg.tip_day = ""
    monkeypatch.setattr(w, "isVisible", lambda: True)
    opened = []
    monkeypatch.setattr(w, "open_settings", lambda page="privacy": opened.append(page))
    assert w._maybe_tip()
    assert not w.tip_bar.isHidden() and "Tabs" in w.tip_lbl.text()
    assert "tabs" in w.cfg.tips_seen and w.cfg.tip_day == tips.today()
    w.tip_btn.click()
    assert opened == ["tabs"] and w.tip_bar.isHidden()
    assert w._maybe_tip() and w.tip_bar.isHidden()   # not again today


def test_window_waits_while_a_game_is_up(window, monkeypatch):  # noqa: F811
    w = window
    w.cfg.setup_done, w.cfg.tips_seen, w.cfg.tip_day = True, [], ""
    monkeypatch.setattr(w, "isVisible", lambda: True)
    monkeypatch.setattr(tips, "fullscreen_in_front", lambda: True)
    assert not w._maybe_tip() and w.tip_bar.isHidden()
    monkeypatch.setattr(tips, "fullscreen_in_front", lambda: False)
    w.overlay.is_open = True
    try:
        assert not w._maybe_tip()
    finally:
        w.overlay.is_open = False
    assert w._maybe_tip() and not w.tip_bar.isHidden()
    w.set_tips_on(False)
    assert w.tip_bar.isHidden() and not w.cfg.tips_on
