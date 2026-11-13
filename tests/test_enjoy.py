"""*Enjoying Onion Board?*: when it's due (enjoy.py), what it sends (usage.survey) and
the card (ui/window/enjoycontrol.py)."""
import time

import pytest
from conftest import own_module
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard.core import enjoy, usage
from soundboard.sounds.library import Config

DAY = 86400.0
NOON = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1))


@pytest.fixture(autouse=True)
def _fresh_run():
    enjoy.forget_run()
    yield
    enjoy.forget_run()


def busy(cfg, day, things=enjoy.DAY_ACTIONS):
    """`things` done on day `day` (days after NOON)."""
    enjoy.forget_run()
    enjoy.add(cfg, 0, 0)
    enjoy.add(cfg, things, 0, NOON + day * DAY)


def test_due_on_a_later_day_after_two_busy_days():
    c = Config()
    busy(c, 0)
    busy(c, 4, enjoy.DAY_ACTIONS - 1)   # one short: doesn't count
    assert enjoy.busy_days(c, NOON + 5 * DAY) == 1 and not enjoy.due(c, NOON + 5 * DAY)
    busy(c, 6)
    assert not enjoy.due(c, NOON + 6 * DAY)   # today never counts: asked on a later day
    assert enjoy.busy_days(c, NOON + 9 * DAY) == 2 and enjoy.due(c, NOON + 9 * DAY)


def test_open_time_alone_never_asks(monkeypatch):
    """Hours open with nothing played or used: no day counts."""
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage.net, "allowed", lambda feature: True)
    monkeypatch.setattr(usage, "_use_counts", {})
    c = Config()
    for i in range(10):
        usage.open_tick(c, 1000.0 + i * 60)
    assert not c.enjoy_days and not enjoy.due(c, NOON + 30 * DAY)


def test_plays_and_features_used_feed_today(monkeypatch):
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage.net, "allowed", lambda feature: True)
    counts: dict = {}
    monkeypatch.setattr(usage, "_use_counts", counts)
    plays = [0]
    monkeypatch.setattr(usage, "total_plays", lambda cfg: plays[0])
    c = Config()
    usage.open_tick(c, 1000.0)   # the first tick only notes the totals
    plays[0] = 7
    counts["voice"] = 2
    usage.open_tick(c, 1060.0)
    assert c.enjoy_days == {enjoy.today(): 9}
    monkeypatch.setattr(usage, "enabled", lambda: False)   # count off: nothing piles up
    plays[0] = 50
    usage.open_tick(c, 1120.0)
    assert c.enjoy_days == {enjoy.today(): 9}


def test_shown_once_ever_and_then_stops_counting():
    c = Config()
    busy(c, 0)
    busy(c, 1)
    assert enjoy.due(c, NOON + 3 * DAY)
    enjoy.asked(c)
    days = dict(c.enjoy_days)
    busy(c, 2, 500)
    assert not enjoy.due(c, NOON + 3 * DAY) and c.enjoy_days == days


def test_keeps_only_the_newest_dates():
    c = Config()
    for i in range(enjoy.KEEP_DAYS + 10):
        busy(c, i, 1)
    assert len(c.enjoy_days) == enjoy.KEEP_DAYS
    assert enjoy.today(NOON + (enjoy.KEEP_DAYS + 9) * DAY) in c.enjoy_days


def test_bad_saved_values_dont_break_it():
    c = Config(enjoy_days={"x": "nope", "y": None})
    busy(c, 0)
    busy(c, 1)
    assert enjoy.busy_days(c, NOON + 5 * DAY) == 2
    c.enjoy_days = "garbage"
    busy(c, 0, 3)
    assert c.enjoy_days == {enjoy.today(NOON): 3}


def test_survey_sends_fixed_names_and_cleaned_words(monkeypatch):
    sent = []
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage.net, "allowed", lambda feature: True)
    monkeypatch.setattr(usage, "send", lambda events, *a, **k: sent.append((events, k)))

    class Now:   # run the send thread inline
        def __init__(self, target, args, kwargs=None, **kw):
            self.go = lambda: target(*args, **(kwargs or {}))

        def start(self):
            self.go()

    own_module(monkeypatch, usage, "threading", Thread=Now)   # (usage's alone)
    assert usage.survey("abc", "positive", "Love it! mail me@example.com 0211234567")
    assert usage.survey("abc", "negative")
    assert usage.survey("abc", "shown", "ignored")
    assert not usage.survey("abc", "made-up")
    assert [e[0][0]["name"] for e in sent] == ["feedback"] * 3
    attrs = [e[0][0].get("attrs") for e in sent]
    assert attrs[0]["what"] == "positive" and "example.com" not in attrs[0]["said"]
    assert "0211234567" not in attrs[0]["said"] and attrs[0]["said"].startswith("love-it")
    assert attrs[1] == {"what": "negative"} and attrs[2] == {"what": "shown"}
    assert {e[1]["install"] for e in sent} == {usage.user_tag("abc")}   # never this PC's ID
    monkeypatch.setattr(usage, "enabled", lambda: False)
    assert not usage.survey("abc", "positive")


def _ready(w, monkeypatch, sent):
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage, "survey", lambda sid, what, said="": sent.append((what, said)))
    monkeypatch.setattr(w, "isVisible", lambda: True)
    monkeypatch.setattr(w, "isActiveWindow", lambda: True)
    w.enjoyctl.due = True


def test_card_thumb_then_words(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    c = w.enjoyctl
    assert c.maybe_show() and c.is_open and c.scrim.isVisibleTo(w)
    assert w.cfg.enjoy_state == "done"   # once, ever: from the moment it shows
    c.up.click()
    assert c.is_open and c.said is not None
    c.said.setText("the voice changer")
    c.said.returnPressed.emit()   # Enter sends
    assert not c.is_open
    assert sent == [("shown", ""), ("positive", ""), ("positive", "the voice changer")]
    assert c.maybe_show() and not c.is_open   # never again


def test_closing_it_counts_as_dismissed(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    c = w.enjoyctl
    c.show()
    c.frame.close_btn.click()
    assert not c.is_open and w.cfg.enjoy_state == "done"
    assert sent == [("shown", ""), ("dismissed", "")]
    c.show()
    c.scrim.mousePressEvent(type("E", (), {"accept": lambda self: None})())   # a click outside
    assert not c.is_open and sent[-1] == ("dismissed", "")


def test_skip_after_a_thumb_sends_no_words(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    c = w.enjoyctl
    c.show()
    c.down.click()
    c.said.setText("")
    c.send_said()
    assert not c.is_open and sent == [("shown", ""), ("negative", "")]


def test_card_fits_a_narrow_window(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    w.resize(1280, 760)
    c = w.enjoyctl
    c.show()
    w.resize(440, 640)
    c._place()
    g = c.frame.geometry()
    assert g.left() >= 0 and g.right() < w.width() and g.bottom() < w.height()
    assert c.scrim.geometry() == w.rect()
    c.close()


def test_card_waits_for_a_calm_moment(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    c = w.enjoyctl
    w.overlay.is_open = True   # the in-game overlay up: wait
    try:
        assert not c.maybe_show() and not c.is_open
    finally:
        w.overlay.is_open = False
    monkeypatch.setattr(w, "isActiveWindow", lambda: False)   # another program in front
    assert not c.maybe_show()
    monkeypatch.setattr(w, "isVisible", lambda: False)   # in the tray: wait
    assert not c.maybe_show()
    monkeypatch.setattr(w, "isVisible", lambda: True)
    monkeypatch.setattr(w, "isActiveWindow", lambda: True)
    assert c.maybe_show() and c.is_open
    assert sent == [("shown", "")]
    c.close()


def test_gives_up_until_the_next_start(window, monkeypatch):  # noqa: F811
    from soundboard.ui.window import enjoycontrol
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    monkeypatch.setattr(w, "isActiveWindow", lambda: False)
    c = w.enjoyctl
    for _ in range(enjoycontrol.TRIES - 1):
        assert not c.maybe_show()
    assert c.maybe_show() and not c.is_open and w.cfg.enjoy_state == ""   # asked next time


def test_never_asks_with_the_count_off_or_not_due(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    monkeypatch.setattr(usage, "enabled", lambda: False)
    assert w.enjoyctl.maybe_show() and not w.enjoyctl.is_open
    monkeypatch.setattr(usage, "enabled", lambda: True)
    w.enjoyctl.due = False
    assert w.enjoyctl.maybe_show() and not w.enjoyctl.is_open
    assert sent == []
