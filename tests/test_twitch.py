"""Connect Twitch: the calls to Twitch (soundboard.online.twitch, with a stand-in for its
servers) and the live link (soundboard.control.twitchlink) turning its events into
alerts and chat commands."""
import io
import json
import urllib.error

import numpy as np
import pytest

from conftest import process_events
from soundboard.control import streamapi, twitchlink
from soundboard.online import net, twitch
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


class FakeTwitch:
    """Answers net.urlopen like Twitch would; `answers[(method, path)]` is (status, body)."""

    def __init__(self):
        self.calls = []
        self.answers = {}

    def __call__(self, req, timeout=30, feature=None, direct=False):
        assert feature == "twitch"
        path = req.full_url.split("?")[0].replace("https://id.twitch.tv", "").replace(
            "https://api.twitch.tv", "")
        body = req.data.decode() if req.data else ""
        self.calls.append((req.get_method(), path, body, dict(req.header_items())))
        status, out = self.answers.get((req.get_method(), path), (200, {}))
        raw = json.dumps(out).encode()
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "no", {}, io.BytesIO(raw))
        return io.BytesIO(raw)


@pytest.fixture
def fake(monkeypatch):
    f = FakeTwitch()
    monkeypatch.setattr(net, "urlopen", f)
    monkeypatch.setattr(twitch, "CLIENT_ID", "test-client")
    return f


def test_signing_in_asks_for_a_code_then_waits_for_the_yes(fake):
    fake.answers[("POST", "/oauth2/device")] = (200, {
        "device_code": "dev-1", "user_code": "ABCD-EFGH", "interval": 5, "expires_in": 1800,
        "verification_uri": "https://www.twitch.tv/activate?public=true&device-code=ABCD"})
    code = twitch.start_login()
    assert (code.user_code, code.device_code, code.interval) == ("ABCD-EFGH", "dev-1", 5.0)
    method, path, body, headers = fake.calls[-1]
    assert "client_id=test-client" in body and "channel%3Aread%3Aredemptions" in body
    fake.answers[("POST", "/oauth2/token")] = (400, {"status": 400,
                                                     "message": "authorization_pending"})
    assert twitch.finish_login("dev-1") is None
    fake.answers[("POST", "/oauth2/token")] = (400, {"status": 400, "message": "access_denied"})
    with pytest.raises(twitch.TwitchError):
        twitch.finish_login("dev-1")
    fake.answers[("POST", "/oauth2/token")] = (200, {"access_token": "a1", "refresh_token": "r1"})
    assert twitch.finish_login("dev-1") == twitch.Tokens("a1", "r1")


def test_helix_calls(fake):
    fake.answers[("GET", "/helix/channel_points/custom_rewards")] = (200, {"data": [
        {"title": "Hydrate"}, {"title": "honk"}, {"title": " "}, {"title": "Hydrate"}]})
    assert twitch.rewards("tok", "42") == ["honk", "Hydrate"]
    assert fake.calls[-1][3]["Authorization"] == "Bearer tok"
    assert fake.calls[-1][3]["Client-id"] == "test-client"
    fake.answers[("GET", "/helix/channel_points/custom_rewards")] = (403, {"message": "no"})
    assert twitch.rewards("tok", "42") == []           # no channel points yet
    # every event asked for on the socket; one refused doesn't stop the rest
    seen = []

    def sub(req, timeout=30, feature=None, direct=False):
        b = json.loads(req.data)
        seen.append(b)
        if b["type"].startswith("channel.channel_points"):
            raise urllib.error.HTTPError(req.full_url, 403, "no", {}, io.BytesIO(b"{}"))
        return io.BytesIO(b"{}")
    net.urlopen = sub
    refused = twitch.subscribe("tok", "42", "sess-1")
    assert refused == ["channel.channel_points_custom_reward_redemption.add"]
    assert len(seen) == len(twitch.SUBSCRIPTIONS)
    follow = next(b for b in seen if b["type"] == "channel.follow")
    assert follow["condition"] == {"broadcaster_user_id": "42", "moderator_user_id": "42"}
    assert follow["transport"] == {"method": "websocket", "session_id": "sess-1"}
    assert next(b for b in seen if b["type"] == "channel.raid")["condition"] == {
        "to_broadcaster_user_id": "42"}


def test_switched_off_means_nothing_is_sent(monkeypatch):
    monkeypatch.setattr(twitch, "CLIENT_ID", "test-client")
    net.configure_features(off=["twitch"])
    with pytest.raises(twitch.TwitchError):
        twitch.validate("tok")
    net.configure_features(offline=True)
    with pytest.raises(twitch.TwitchError):
        twitch.start_login()


# --------------------------------------------------------------------------- the live link

@pytest.fixture
def window(main_window, monkeypatch):  # noqa: F811
    w = main_window
    for sid in ("s0", "s1"):
        w.audio[sid] = np.zeros((480, 2), np.float32)
    w.played = []
    w.playctl.play = w.played.append
    monkeypatch.setattr(twitch, "CLIENT_ID", "test-client")
    return w


class Link:
    """The window's TwitchLink with Twitch's calls stood in for and no real socket."""

    def __init__(self, w, monkeypatch):
        self.w = w
        self.calls = []
        self.opened = []
        self.validate_status = 200
        link = self.link = w.twitch
        for name in ("start_login", "finish_login", "validate", "refresh", "rewards",
                     "subscribe", "send_chat", "revoke"):
            monkeypatch.setattr(twitch, name, getattr(self, name))
        monkeypatch.setattr(link, "_open", lambda url, moving=False: self.opened.append(
            (url, moving)) or setattr(link, "_next" if moving else "_sock", object()))
        monkeypatch.setattr(link, "_drop",
                            lambda s: s is not None and self.calls.append(("drop", s)))

    def start_login(self):
        self.calls.append(("start_login",))
        return twitch.DeviceCode("dev", "WXYZ", "https://www.twitch.tv/activate", 0.01, 60)

    def finish_login(self, code):
        self.calls.append(("finish_login", code))
        n = sum(c[0] == "finish_login" for c in self.calls)
        return None if n < 2 else twitch.Tokens("tok", "ref")

    def validate(self, token):
        self.calls.append(("validate", token))
        if self.validate_status == 401 and token == "tok":
            raise twitch.TwitchError("invalid", 401)
        return {"login": "streamer", "user_id": "42"}

    def refresh(self, token):
        self.calls.append(("refresh", token))
        return twitch.Tokens("tok2", "ref2")

    def rewards(self, token, uid):
        return ["Honk", "Hydrate"]

    def subscribe(self, token, uid, sid):
        self.calls.append(("subscribe", token, uid, sid))
        return []

    def send_chat(self, token, uid, msg):
        self.calls.append(("send_chat", msg))

    def revoke(self, token):
        self.calls.append(("revoke", token))

    def message(self, mtype, payload, mid="", sock=None):
        self.link._message(sock or self.link._sock, json.dumps(
            {"metadata": {"message_type": mtype, "message_id": mid}, "payload": payload}))

    def welcome(self, sid="sess-1", sock=None):
        self.message("session_welcome", {"session": {"id": sid, "keepalive_timeout_seconds": 30}},
                     sock=sock)


def notification(kind, event):
    return {"subscription": {"type": kind}, "event": event}


def test_connect_signs_in_then_listens(qapp, window, monkeypatch):
    w = window
    t = Link(w, monkeypatch)
    codes, done = [], []
    t.link.code_ready.connect(lambda c, u: codes.append((c, u)))
    t.link.login_done.connect(lambda ok, m: done.append((ok, m)))
    t.link.login()
    assert process_events(qapp, lambda: done)
    assert codes == [("WXYZ", "https://www.twitch.tv/activate")] and done == [(True, "streamer")]
    cfg = w.cfg
    assert (cfg.twitch_token, cfg.twitch_refresh, cfg.twitch_login, cfg.twitch_user_id) == (
        "tok", "ref", "streamer", "42")
    assert process_events(qapp, lambda: t.opened)
    assert t.opened == [(twitch.EVENTSUB_WS, False)] and t.link.state == twitchlink.CONNECTING
    t.welcome()
    assert process_events(qapp, lambda: t.link.state == twitchlink.ON)
    assert ("subscribe", "tok", "42", "sess-1") in t.calls
    assert process_events(qapp, lambda: t.link.rewards == ["Honk", "Hydrate"])
    # the tokens never go into a backup
    from soundboard.core import backup
    assert {"twitch_token", "twitch_refresh"} <= backup.LOCAL_SETTINGS


def test_events_play_what_the_alerts_say(qapp, window, monkeypatch):
    w = window
    t = Link(w, monkeypatch)
    w.cfg.twitch_token, w.cfg.twitch_user_id = "tok", "42"
    streamapi.set_alerts(w, {"type": "redeem", "reward": "Honk", "sound": "Airhorn"})
    streamapi.set_alerts(w, {"type": "follow", "sound": "Boom"})
    t.link.apply()
    assert process_events(qapp, lambda: t.opened)
    t.welcome()
    redeem = notification("channel.channel_points_custom_reward_redemption.add",
                          {"id": "r1", "user_name": "Ann", "reward": {"title": "Honk"}})
    t.message("notification", redeem, mid="m1")
    assert w.played == ["s1"]
    t.message("notification", redeem, mid="m1")           # Twitch sent it twice
    assert w.played == ["s1"]
    t.message("notification", notification("channel.follow", {"user_name": "Bo"}), mid="m2")
    assert w.played == ["s1", "s0"]


def test_chat_commands_and_their_replies(qapp, window, monkeypatch):
    w = window
    t = Link(w, monkeypatch)
    w.cfg.twitch_token, w.cfg.twitch_user_id = "tok", "42"

    def line(text, mid, badges=()):
        return notification("channel.chat.message", {
            "chatter_user_name": "Viewer", "message": {"text": text},
            "badges": [{"set_id": b} for b in badges]}), mid
    status, body = t.link.handle(*line("!sound airhorn", "c1"))
    assert body["handled"] and w.played == ["s1"]
    status, body = t.link.handle(*line("!sounds", "c2", badges=("moderator",)))
    assert body["reply"]
    assert process_events(qapp, lambda: any(c[0] == "send_chat" for c in t.calls))
    assert ("send_chat", body["reply"]) in t.calls
    # a mod badge counts as a mod: !stop is for mods
    status, body = t.link.handle(*line("!stop", "c3"))
    assert not body["handled"]
    status, body = t.link.handle(*line("!stop", "c4", badges=("moderator",)))
    assert body["handled"]


def test_an_old_token_is_refreshed_and_kept(qapp, window, monkeypatch):
    w = window
    t = Link(w, monkeypatch)
    t.validate_status = 401
    w.cfg.twitch_token, w.cfg.twitch_refresh, w.cfg.twitch_user_id = "tok", "ref", "42"
    t.link.apply()
    assert process_events(qapp, lambda: t.opened)
    assert ("refresh", "ref") in t.calls
    assert (w.cfg.twitch_token, w.cfg.twitch_refresh) == ("tok2", "ref2")


def test_switched_off_or_disconnected_it_stays_away(qapp, window, monkeypatch):
    w = window
    t = Link(w, monkeypatch)
    w.cfg.twitch_token, w.cfg.twitch_user_id = "tok", "42"
    net.configure_features(off=["twitch"])
    t.link.apply()
    assert t.link.state == twitchlink.PROBLEM and "Privacy" in t.link.message
    process_events(qapp, lambda: False, timeout=0.2)
    assert not t.opened and not t.calls
    net.configure_features()          # back on: it connects by itself
    assert process_events(qapp, lambda: t.opened)
    t.link.disconnect()
    assert w.cfg.twitch_token == "" and w.cfg.twitch_login == ""
    assert t.link.state == twitchlink.OFF
    assert process_events(qapp, lambda: ("revoke", "tok") in t.calls)


def test_the_socket_moving_and_going_quiet(qapp, window, monkeypatch):
    w = window
    t = Link(w, monkeypatch)
    w.cfg.twitch_token, w.cfg.twitch_user_id = "tok", "42"
    t.link.apply()
    assert process_events(qapp, lambda: t.opened)
    t.welcome()
    assert process_events(qapp, lambda: t.link.state == twitchlink.ON)
    old = t.link._sock
    t.message("session_reconnect", {"session": {"reconnect_url": "wss://eventsub.example/ws?x"}})
    assert t.opened[-1] == ("wss://eventsub.example/ws?x", True)
    new = t.link._next
    t.welcome("sess-2", sock=new)
    assert t.link._sock is new and ("drop", old) in t.calls
    assert sum(c[0] == "subscribe" for c in t.calls) == 1   # the subscriptions moved with it
    t.message("session_reconnect", {"session": {"reconnect_url": "http://evil.example/"}})
    assert len(t.opened) == 2                                # only Twitch's wss:// moves it
    t.link._went_quiet()
    assert t.link.state == twitchlink.PROBLEM and t.link._retry.isActive()


def test_the_settings_card(qapp, window, monkeypatch):
    from soundboard.ui.kit import busy
    from soundboard.ui.settings import twitchcard
    w = window
    monkeypatch.setattr(busy, "toast", lambda *a, **k: None)
    monkeypatch.setattr(w.twitch, "apply", lambda: None)
    w.cfg.twitch_token, w.cfg.twitch_login, w.cfg.twitch_user_id = "tok", "streamer", "42"
    w.twitch.rewards = ["Honk", "Hydrate"]
    w.twitch.state = twitchlink.ON
    w.setctl.open_settings("remote")
    process_events(qapp, lambda: w.setctl._settings_dlg is not None)
    card = w.setctl._settings_dlg.findChildren(twitchcard.TwitchCard)[0]
    assert card.pill.text() == "Connected" and card.on.isVisibleTo(card.card)
    box = card.reward_pickers["Honk"]
    box.setCurrentIndex(box.findData("Airhorn"))
    box.activated.emit(box.currentIndex())
    assert twitchcard.rule_for(w, "redeem", "honk")["sound"] == "Airhorn"
    raid = card.alert_pickers["raid"]
    raid.setCurrentIndex(raid.findData(twitchcard.RANDOM))
    raid.activated.emit(raid.currentIndex())
    assert twitchcard.rule_for(w, "raid")["category"] == "*"
    raid.setCurrentIndex(0)   # Nothing
    raid.activated.emit(0)
    assert twitchcard.rule_for(w, "raid") is None
    # a reward gone from Twitch: its row goes too, at once
    old = card.reward_pickers["Hydrate"]
    w.twitch.rewards = ["Honk"]
    w.twitch.changed.emit()
    assert list(card.reward_pickers) == ["Honk"] and old.parent() is None
    assert card.reward_pickers["Honk"].currentData() == "Airhorn"
    # set some other way (/api/alerts with a line to say): shown as such, never overwritten
    streamapi.set_alerts(w, {"type": "follow", "say": "Thanks {user}"})
    w.twitch.changed.emit()
    follow = card.alert_pickers["follow"]
    assert follow.currentData() == "elsewhere"
    follow.activated.emit(follow.currentIndex())
    assert twitchcard.rule_for(w, "follow")["say"] == "Thanks {user}"
    card.chat.setChecked(False)
    assert streamapi.chat_rules(w)["on"] is False
    disconnected = []
    monkeypatch.setattr(w.twitch, "disconnect", lambda: disconnected.append(1))
    card.btn_disconnect.click()
    assert disconnected


def test_no_card_without_a_client_id(qapp, window, monkeypatch):
    from soundboard.ui.settings import twitchcard
    monkeypatch.setattr(twitch, "CLIENT_ID", "")
    window.setctl.open_settings("remote")
    process_events(qapp, lambda: window.setctl._settings_dlg is not None)
    assert not window.setctl._settings_dlg.findChildren(twitchcard.TwitchCard)


def test_the_cards_guide_and_ai_prompt(qapp, window, monkeypatch):
    from PySide6.QtWidgets import QApplication, QPushButton
    from soundboard.ui.kit import busy
    from soundboard.ui.settings import twitchcard, twitchguide
    w = window
    monkeypatch.setattr(busy, "toast", lambda *a, **k: None)
    monkeypatch.setattr(w.twitch, "apply", lambda: None)
    w.cfg.twitch_token, w.cfg.twitch_login, w.cfg.twitch_user_id = "tok", "streamer", "42"
    w.twitch.rewards = ["Honk", "Hydrate"]
    w.twitch.state = twitchlink.ON
    w.cfg.api_token = "secret-key-123"
    twitchcard.set_rule(w, "redeem", "Airhorn", "Honk")
    twitchcard.set_rule(w, "raid", twitchcard.RANDOM)
    # what's set now goes in, the secrets never do
    p = twitchguide.twitch_prompt(w)
    assert "signed in as streamer" in p
    assert '"Honk": the sound "Airhorn"' in p and '"Hydrate": nothing' in p
    assert "- raid: a random sound" in p and "- Airhorn" in p
    assert "YOUR-KEY" in p and "secret-key-123" not in p and "tok" not in p.split()
    # both buttons on the card: the AI prompt is copied, the guide opens
    w.setctl.open_settings("remote")
    process_events(qapp, lambda: w.setctl._settings_dlg is not None)
    card = w.setctl._settings_dlg.findChildren(twitchcard.TwitchCard)[0]
    shown = [b for b in card.on.findChildren(QPushButton) if b.isVisibleTo(card.card)]
    ai = next(b for b in shown if b.text() == "Copy AI prompt")
    ai.click()
    assert QApplication.clipboard().text() == p
    opened = []
    monkeypatch.setattr(twitchguide.TwitchGuide, "exec", lambda self: opened.append(self) or 0)
    next(b for b in shown if b.text() == "Twitch guide").click()
    assert len(opened) == 1
