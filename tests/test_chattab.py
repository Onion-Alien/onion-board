"""The Chat tab (ui/chattab.py), against a fake room: no test goes online."""
import time

import pytest
from conftest import process_events as spin

from soundboard import chat, net
from soundboard.library import Config
from soundboard.ui import chattab
from soundboard.ui.tabcontrol import TAB_KEYS, rail_order


def _wait(qapp, cond, secs=5.0):
    return spin(qapp, cond, timeout=secs)


def process_events(qapp):
    spin(qapp, lambda: False, timeout=0.1)


class FakeRoom:
    """Stands in for chat.poll / say / report: keeps the room's messages."""

    def __init__(self):
        self.msgs = []
        self.reports = []
        self.said = []
        self.fail = ""

    def add(self, text, user="u1", name="SoggyGoblin42"):
        i = len(self.msgs) + 1
        self.msgs.append(chat.Message(i, 1000 + i, user, name, text))

    def poll(self, install, after, wait=True):
        if self.fail:
            raise chat.ChatError(self.fail)
        out = [m for m in self.msgs if m.id > after]
        if not out and wait:
            time.sleep(0.05)
        return out, len(self.msgs), False

    def say(self, install, text):
        self.said.append(text)
        self.add(text, user="me", name="CursedPotato10")
        return self.msgs[-1]

    def report(self, install, mid):
        self.reports.append(mid)


@pytest.fixture
def room(monkeypatch):
    r = FakeRoom()
    monkeypatch.setattr(chat, "poll", r.poll)
    monkeypatch.setattr(chat, "say", r.say)
    monkeypatch.setattr(chat, "report", r.report)
    return r


def _tab(qapp, accepted=True, counted=None):
    cfg = Config()
    if accepted:
        cfg.chat_rules = chat.RULES_VERSION
    t = chattab.ChatTab(cfg, lambda: None, lambda: None,
                        (counted if counted is not None else []).append)
    t.resize(800, 600)
    t.show()
    return t


def test_chat_is_last_in_the_tab_list_and_before_setup_on_the_rail():
    assert TAB_KEYS[-2:] == ("store", "chat")
    assert rail_order([])[-3:] == ["store", "chat", "setup"]
    assert rail_order(["chat", "sounds", "setup"]) == [
        "chat", "sounds", "store", "setup", "radio", "apps", "triggers", "voice"]


def test_it_starts_switched_off_for_everyone():
    assert "chat" in Config.first_start().tabs_off
    raw = {"tabs_off": ["radio"]}
    assert Config.from_raw(dict(raw)).tabs_off == ["radio", "chat"]   # saved before chat
    assert "chat" in Config.from_raw({}).tabs_off
    on = Config.from_raw({"chat_rules": 1, "tabs_off": []})   # switched on since
    assert on.tabs_off == []


def test_rules_come_first_and_nothing_goes_online_until_accepted(qapp, room):
    counted = []
    t = _tab(qapp, accepted=False, counted=counted)
    assert t.stack.currentWidget() is t.message_area and not t.entry.isEnabled()
    assert "agree" in t.msg_btn.text().lower()
    room.add("early")
    process_events(qapp)
    assert not t._rows
    t.msg_btn.click()
    assert t.cfg.chat_rules == chat.RULES_VERSION and counted == ["chat-joined"]
    assert _wait(qapp, lambda: len(t._rows) == 1)
    t.shutdown()


def test_messages_show_as_plain_text_and_new_ones_arrive(qapp, room):
    room.add("<b>hi</b> & <img src=x>")
    t = _tab(qapp)
    assert _wait(qapp, lambda: len(t._rows) == 1)
    assert t._rows[0].text.text() == "<b>hi</b> & <img src=x>"
    assert t._rows[0].text.textFormat() == chattab.Qt.TextFormat.PlainText
    room.add("second")
    assert _wait(qapp, lambda: len(t._rows) == 2)
    t.shutdown()


def test_sending_shows_your_message_once_and_counts_the_first(qapp, room):
    counted = []
    t = _tab(qapp, counted=counted)
    assert _wait(qapp, lambda: t.stack.currentWidget() is t.message_area)   # an empty room
    t.entry.setText("  hello   world ")
    t.send()
    assert _wait(qapp, lambda: room.said == ["hello world"])
    assert _wait(qapp, lambda: len(t._rows) == 1)
    process_events(qapp)
    time.sleep(0.2)
    process_events(qapp)
    assert len(t._rows) == 1 and t.entry.text() == "" and "chat-said" in counted
    assert t._rows[0].who.text().count("You")
    t.shutdown()


def test_mute_hides_a_name_and_report_goes_once(qapp, room):
    room.add("rude", user="bad", name="FeralGremlin11")
    room.add("nice", user="ok", name="TinyOtter12")
    room.add("rude again", user="bad", name="FeralGremlin11")
    t = _tab(qapp)
    assert _wait(qapp, lambda: len(t._rows) == 3)
    t._rows[1].btn_report.click()
    assert _wait(qapp, lambda: room.reports == [2])
    assert _wait(qapp, lambda: t._rows[1].btn_report.isEnabled() is False)
    t._rows[0].btn_mute.click()
    assert [r.message.user for r in t._rows] == ["ok"]
    room.add("still rude", user="bad", name="FeralGremlin11")
    assert _wait(qapp, lambda: len(room.msgs) == 4)
    time.sleep(0.3)
    process_events(qapp)
    assert [r.message.user for r in t._rows] == ["ok"]
    t.shutdown()


def test_a_failed_poll_says_why_and_retries(qapp, room):
    room.fail = "Couldn't reach chat. Check your internet."
    t = _tab(qapp)
    assert _wait(qapp, lambda: t.stack.currentWidget() is t.message_area
                 and t.msg_btn.isVisibleTo(t))
    assert room.fail in t.msg_text.text()
    room.fail = ""
    room.add("back")
    t.msg_btn.click()
    assert _wait(qapp, lambda: len(t._rows) == 1)
    t.shutdown()


def test_switched_off_contacts_nobody(qapp, room, monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda f: f != chat.FEATURE)
    seen = []
    monkeypatch.setattr(chat, "poll", lambda *a, **k: seen.append(a) or ([], 0, False))
    t = _tab(qapp)
    process_events(qapp)
    assert t.stack.currentWidget() is t.message_area and not t.entry.isEnabled()
    assert "off" in t.msg_title.text().lower() and not seen
    t.shutdown()


def test_hiding_the_tab_stops_the_polling(qapp, room):
    t = _tab(qapp)
    assert _wait(qapp, lambda: t._polling)
    gen = t._gen
    t.hide()
    assert t._gen > gen and not t._polling
    t.shutdown()


def test_an_empty_room_is_not_asked_over_and_over(qapp, room, monkeypatch):
    calls = []

    def poll(install, after, wait=True):
        calls.append(wait)
        return [], 0, False   # an empty room that answers at once, whatever it's asked
    monkeypatch.setattr(chat, "poll", poll)
    t = _tab(qapp)
    _wait(qapp, lambda: False, secs=1.6)
    t.shutdown()
    assert 1 <= len(calls) <= 3, calls       # about one a second, never a flood
    assert calls[0] is False and all(calls[1:])   # only the first look doesn't wait
