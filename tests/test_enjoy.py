"""*Enjoying Onion Board?*: when it's due (enjoy.py), what it sends (usage.survey) and
the bar (ui/enjoycontrol.py)."""
import time

from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard import enjoy, usage
from soundboard.library import Config

DAY = 86400.0
NOON = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1))


def heavy_days(cfg, n, hours=2.5):
    for i in range(n):
        enjoy.add(cfg, hours * 3600, NOON + i * DAY)


def test_due_after_three_busy_days_not_in_a_row():
    c = Config()
    heavy_days(c, 2)
    enjoy.add(c, 3600, NOON + 5 * DAY)          # an hour: doesn't count
    assert enjoy.busy_days(c) == 2 and not enjoy.due(c)
    enjoy.add(c, 2 * 3600, NOON + 9 * DAY)      # a week later, 2 hours: the third
    assert enjoy.busy_days(c) == 3 and enjoy.due(c)


def test_one_long_day_or_many_short_ones_never_ask():
    c = Config()
    enjoy.add(c, 20 * 3600, NOON)
    for i in range(1, 25):
        enjoy.add(c, 1.5 * 3600, NOON + i * DAY)
    assert not enjoy.due(c)


def test_shown_once_ever_and_then_stops_counting():
    c = Config()
    heavy_days(c, 3)
    assert enjoy.due(c)
    enjoy.asked(c)
    days = dict(c.enjoy_days)
    enjoy.add(c, 5000, NOON + 40 * DAY)
    assert not enjoy.due(c) and c.enjoy_days == days


def test_keeps_only_the_newest_dates():
    c = Config()
    for i in range(enjoy.KEEP_DAYS + 10):
        enjoy.add(c, 60, NOON + i * DAY)
    assert len(c.enjoy_days) == enjoy.KEEP_DAYS
    assert enjoy.today(NOON + (enjoy.KEEP_DAYS + 9) * DAY) in c.enjoy_days


def test_bad_saved_values_dont_break_it():
    c = Config(enjoy_days={"x": "nope", "y": None})
    heavy_days(c, 3)
    assert enjoy.busy_days(c) == 3 and enjoy.due(c)
    c.enjoy_days = "garbage"
    enjoy.add(c, 10, NOON)
    assert enjoy.today(NOON) in c.enjoy_days


def test_open_time_feeds_the_day_count(monkeypatch):
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage.net, "allowed", lambda feature: True)
    c = Config()
    usage.open_tick(c, 1000.0)
    usage.open_tick(c, 1300.0)
    assert sum(c.enjoy_days.values()) == 300.0
    monkeypatch.setattr(usage, "enabled", lambda: False)   # count off: nothing piles up
    usage.open_tick(c, 1600.0)
    assert sum(c.enjoy_days.values()) == 300.0


def test_survey_sends_fixed_names_and_cleaned_words(monkeypatch):
    sent = []
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage.net, "allowed", lambda feature: True)
    monkeypatch.setattr(usage, "send", lambda payload, *a, **k: sent.extend(payload))

    class Now:   # run the send thread inline
        def __init__(self, target, args, **kw):
            self.go = lambda: target(*args)

        def start(self):
            self.go()

    monkeypatch.setattr(usage.threading, "Thread", Now)
    assert usage.survey("abc", "positive", "Love it! mail me@example.com 0211234567")
    assert usage.survey("abc", "negative")
    assert usage.survey("abc", "shown", "ignored")
    assert not usage.survey("abc", "made-up")
    assert [h["path"] for h in sent] == ["feedback/positive/love-it-mail",
                                         "feedback/negative", "feedback/shown"]
    assert {h["session"] for h in sent} == {"abc"}
    monkeypatch.setattr(usage, "enabled", lambda: False)
    assert not usage.survey("abc", "positive")


def _ready(w, monkeypatch, sent):
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage, "survey", lambda sid, what, said="": sent.append((what, said)))
    monkeypatch.setattr(w, "isVisible", lambda: True)
    heavy_days(w.cfg, 3)


def test_bar_thumb_then_words(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    assert w.enjoyctl.maybe_show() and not w.enjoy_bar.isHidden()
    assert w.cfg.enjoy_state == "done"   # once, ever: from the moment it shows
    assert w.enjoyctl.up.isVisibleTo(w.enjoy_bar) and w.enjoyctl.answer.isHidden()
    w.enjoyctl.up.click()
    assert w.enjoyctl.answer.isVisibleTo(w.enjoy_bar) and w.enjoyctl.up.isHidden()
    w.enjoyctl.said.setPlainText("the voice changer")
    w.enjoyctl.send_btn.click()
    assert w.enjoy_bar.isHidden()
    assert sent == [("shown", ""), ("positive", ""), ("positive", "the voice changer")]
    assert w.enjoyctl.maybe_show() and w.enjoy_bar.isHidden()   # never again


def test_bar_x_closes_it_for_good(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    w.enjoyctl.show()
    w.enjoyctl.x.click()
    assert w.enjoy_bar.isHidden() and w.cfg.enjoy_state == "done"
    assert sent == [("shown", ""), ("dismissed", "")]
    w.enjoyctl.shown = False   # (a later start)
    assert w.enjoyctl.maybe_show() and w.enjoy_bar.isHidden()


def test_box_wraps_grows_and_enter_sends(window, monkeypatch):  # noqa: F811
    from soundboard.ui import enjoycontrol
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    w.resize(1000, 640)
    w.show()
    c = w.enjoyctl
    c.show()
    c.vote("negative")
    one = c.said.height()
    assert c.send_btn.height() == one   # level with the box's first line
    # the border and padding are counted, so the words aren't squeezed to the top
    assert one >= c.said.fontMetrics().lineSpacing() + (one - c.said.viewport().height())
    c.said.setPlainText("word " * 60)   # past SAID_MAX: cut, and taller (it wraps)
    assert len(c.said.toPlainText()) == enjoycontrol.SAID_MAX
    tallest = enjoycontrol.SAID_LINES * c.said.fontMetrics().lineSpacing() + 30
    assert one < c.said.height() <= tallest
    c.said.setPlainText("too slow\n")      # Enter sends
    assert w.enjoy_bar.isHidden() and sent[-1] == ("negative", "too slow")


def test_bar_waits_for_a_calm_moment(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    w.tip_bar.show()   # another bar up: wait
    assert not w.enjoyctl.maybe_show() and w.enjoy_bar.isHidden()
    w.tip_bar.hide()
    w.overlay.is_open = True   # a game up: wait
    try:
        assert not w.enjoyctl.maybe_show()
    finally:
        w.overlay.is_open = False
    monkeypatch.setattr(w, "isVisible", lambda: False)   # in the tray: wait
    assert not w.enjoyctl.maybe_show()
    monkeypatch.setattr(w, "isVisible", lambda: True)
    assert w.enjoyctl.maybe_show() and not w.enjoy_bar.isHidden()
    assert sent == [("shown", "")]


def test_bar_never_asks_with_the_count_off(window, monkeypatch):  # noqa: F811
    w, sent = window, []
    _ready(w, monkeypatch, sent)
    monkeypatch.setattr(usage, "enabled", lambda: False)
    assert not w.enjoyctl.maybe_show() and w.enjoy_bar.isHidden()
