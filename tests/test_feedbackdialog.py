"""Send feedback's "What would you improve?" box (ui/feedbackdialog.py) and what it
sends (usage.improve / other_tag)."""
from types import SimpleNamespace

from soundboard import __version__, feedback, usage
from soundboard.ui import busy, feedbackdialog


def test_other_tag_keeps_the_words_and_drops_anything_personal():
    assert usage.other_tag("More anime sounds, please!") == "more-anime-sounds-please"
    assert usage.other_tag("mail me at a.b@example.com or 0211234567") == "mail-me-at-or"
    assert usage.other_tag("see https://example.com/x and www.example.org") == "see-and"
    assert usage.other_tag("Mehr Geräusche bitte") == "mehr-geräusche-bitte"
    assert usage.other_tag("   ") == ""
    long = usage.other_tag("word " * 100)
    assert len(long) <= usage.OTHER_MAX and long.endswith("word")


def test_improve_sends_only_known_names_and_the_tidied_other(monkeypatch):
    sent = []
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage.net, "allowed", lambda f: True)
    monkeypatch.setattr(usage, "send", lambda payload: sent.append(payload) or True)
    monkeypatch.setattr(usage.threading, "Thread",
                        lambda target, args, **kw: SimpleNamespace(start=lambda: target(*args)))
    cfg = SimpleNamespace(stats_id="abc")
    assert usage.improve(cfg, ["looks", "nonsense", "other"], "Dark mode me@example.com")
    assert [h["path"] for h in sent[0]] == ["improve/looks", "improve/other/dark-mode"]
    # anonymous: a one-off session per send, never this PC's ID
    sessions = {h["session"] for h in sent[0]}
    assert all(h["event"] for h in sent[0]) and len(sessions) == 1 and "abc" not in sessions
    sent.clear()
    usage.improve(cfg, ["sounds"], "typed but Other not ticked")
    assert [h["path"] for h in sent[0]] == ["improve/sounds"]
    assert sent[0][0]["session"] not in sessions | {"abc"}


def test_improve_sends_nothing_when_the_count_is_off(monkeypatch):
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage.net, "allowed", lambda f: False)
    monkeypatch.setattr(usage, "send", lambda payload: 1 / 0)
    assert not usage.improve(SimpleNamespace(stats_id="abc"), ["sounds"])


def test_every_pick_is_a_counted_name():
    assert [k for k, _t in feedbackdialog.picks()] == list(usage.IMPROVE)


def test_the_box_asks_then_thanks_and_opens_the_form(qapp, monkeypatch):
    calls, opened = [], []
    monkeypatch.setattr(usage, "improve", lambda cfg, picks, other="": calls.append(
        (picks, other)) or False)
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString())
                        or True)
    dlg = feedbackdialog.FeedbackDialog(SimpleNamespace())
    dlg.show()
    assert not dlg.send_btn.isEnabled() and not dlg.other.isVisible()
    dlg.boxes["speed"].setChecked(True)
    dlg.boxes["other"].setChecked(True)
    assert dlg.other.isVisible() and dlg.send_btn.isEnabled()
    dlg.other.setText("a dark theme")
    dlg.send_btn.click()
    assert calls == [(["speed", "other"], "a dark theme")]
    assert dlg.pages.currentIndex() == 1
    assert dlg.not_sent.isVisible()          # the count is off here: say so
    assert "Anonymous" in dlg.anon_note.text()
    dlg.form_btn.click()
    assert opened == [feedback.feedback_url(__version__, improve=["speed", "other"])]
    assert "improve=speed%2Cother" in opened[0]
    dlg.deleteLater()
