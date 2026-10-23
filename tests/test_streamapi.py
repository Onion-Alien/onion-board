"""The control API's streamer endpoints (soundboard.control.streamapi): chat commands, alerts
from bots and donation sites, the feed; and the endpoints for the newer features."""
import http.client
import json
import threading

import numpy as np
import pytest

from conftest import process_events
from soundboard.control import remote, streamapi
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)

TOKEN = "test-token-123"


@pytest.fixture
def window(main_window):  # noqa: F811
    w = main_window
    for sid in ("s0", "s1"):
        w.audio[sid] = np.zeros((480, 2), np.float32)
    w.played = []
    w.playctl.play = w.played.append
    w.said = []
    w.voice.speech.ctl.say = w.said.append
    return w


def d(w, action, **p):
    return remote.dispatch(w, action, p)


def test_chat_commands_play_list_and_wait_their_turn(qapp, window):
    w = window
    st, body = d(w, "chat", user="Ann", message="!sound airhorn")
    assert st == 200 and body["handled"] and body["playing"] == "s1" and w.played == ["s1"]
    st, body = d(w, "chat", user="Ann", message="!sound boom")   # within the cooldowns
    assert not body["handled"] and body["reason"] == "cooldown" and body["wait"] > 0
    st, body = d(w, "chat", user="Mo", message="!sound bo", mod="1")   # mods don't wait
    assert body["handled"] and body["name"] == "Boom"            # (a unique start is enough)
    st, body = d(w, "chat", user="Bea", message="!sounds")
    assert body["handled"] and body["reply"] == "Sounds: Boom, Airhorn"
    st, body = d(w, "chat", user="Mo", message="!sound airhron", mod="1")
    assert not body["handled"] and "Airhorn" in body["reply"] and "@Mo" in body["reply"]
    st, body = d(w, "chat", user="Bea", message="hello everyone")
    assert body == {"handled": False, "user": "Bea", "reply": "", "reason": "not a command"}
    assert d(w, "chat", user="Bea", message="!ban x")[1]["reason"].startswith("not one")
    assert d(w, "chat", user="Bea")[0] == 400


def test_the_list_and_stop_wait_their_turn_too(qapp, window):
    """One viewer can't flood chat with !sounds, and asking for the list doesn't hold up
    the !sound after it. A viewer's !stop waits like a play; a mod's doesn't."""
    w = window
    d(w, "chat_rules", user_cooldown="30", cooldown="0", stop="everyone")
    assert d(w, "chat", user="Ann", message="!sounds")[1]["handled"]
    body = d(w, "chat", user="Ann", message="!sounds")[1]
    assert not body["handled"] and body["reason"] == "cooldown" and body["wait"] > 0
    assert d(w, "chat", user="Bea", message="!sounds")[1]["handled"]   # someone else
    assert d(w, "chat", user="Ann", message="!sound boom")[1]["handled"]
    stopped = []
    w.playctl.stop_all = lambda: stopped.append(1)
    body = d(w, "chat", user="Ann", message="!stop")[1]
    assert body["reason"] == "cooldown" and not stopped
    assert d(w, "chat", user="Mo", message="!stop", mod="1")[1]["handled"]
    assert d(w, "chat", user="Mo", message="!stop", mod="1")[1]["handled"] and stopped == [1, 1]


def test_bidi_overrides_are_taken_out_of_names_and_text(qapp, window):
    """Right-to-left overrides in a name or a line can flip what the feed and the
    overlay show: they're dropped like other control characters."""
    w = window
    d(w, "chat_rules", tts="everyone", cooldown="0", user_cooldown="0")
    body = d(w, "chat", user="‮Ann‬", message="⁧hi⁩ ‪all‬")[1]
    assert body["handled"] and body["user"] == "Ann" and w.said == ["Ann says hi all"]
    assert streamapi.clean_text("a‭b⁦c", {}) == "a b c"


def test_markup_in_chat_isnt_read_out(qapp, window):
    """HTML tags and entities a viewer (or a bridge that escapes chat) sends aren't read
    out letter by letter; "<3", "a < b" and "<your name>" stay as they were typed."""
    w = window
    d(w, "chat_rules", say="everyone", cooldown="0", user_cooldown="0")
    body = d(w, "chat", user="Ann", message="!say <b>bold</b><i>x</i> &amp; &lt;b&gt;")[1]
    assert body["handled"] and w.said == ["boldx &"], body
    d(w, "chat_rules", tts="everyone")
    assert d(w, "chat", user="Bea", message="<i>hi</i> &quot;all&quot;")[1]["handled"]
    assert w.said[-1] == 'Bea says hi "all"'
    assert streamapi.clean_text("<script>alert(1)</script><br/>hi", {}) == "alert(1) hi"
    assert streamapi.clean_text("x&#8238;y &#10;z", {}) == "x y z"   # no way round _CONTROL
    assert streamapi.clean_text("bad<b></b>word &#98;adword", {"blocked": ["badword"]}) is None
    for kept in ("i <3 you >:)", "a < b and c > d", "say <your name> here"):
        assert streamapi.clean_text(kept, {}) == kept


def test_random_names_a_category_outside_chats_one(qapp, window):
    """Under a category limit, !random <another real category> says that's not chat's
    one (it used to answer "no such category", and posted nothing)."""
    w = window
    w.cfg.categories = ["Music", "Memes"]
    for m, tag in zip(w.cfg.sounds, ("Music", "Memes")):
        m.tags = [tag]
    d(w, "chat_rules", category="Music", cooldown="0", user_cooldown="0")
    body = d(w, "chat", user="Ann", message="!random memes")[1]
    assert not body["handled"] and body["reason"] == "not chat's category"
    assert "@Ann" in body["reply"] and "Music" in body["reply"]
    body = d(w, "chat", user="Ann", message="!random Nope")[1]
    assert body["reason"] == "no such category" and "Nope" in body["reply"]
    assert d(w, "chat", user="Ann", message="!random music")[1]["handled"]


def test_who_may_use_each_command(qapp, window):
    w = window
    assert d(w, "chat", user="Ann", message="!say hi")[1]["reason"] == "not allowed"
    assert d(w, "chat", user="Ann", message="!stop")[1]["reason"] == "not allowed"
    st, rules = d(w, "chat_rules", say="subs", cooldown="0", user_cooldown="0")
    assert st == 200 and rules["rules"]["say"] == "subs" and rules["rules"]["cooldown"] == 0
    assert w.cfg.api_stream["chat"]["say"] == "subs"
    assert d(w, "chat", user="Ann", message="!say hi")[1]["reason"] == "not allowed"
    # Twitch's badges tag, as a bot passes it on
    st, body = d(w, "chat", user="Ann", message="!say hi chat", badges="subscriber/12")
    assert body["handled"] and w.said == ["hi chat"]
    assert d(w, "chat", user="Bo", message="!say yo", broadcaster="true")[1]["handled"]
    assert d(w, "chat_rules", say="admins")[0] == 400
    assert d(w, "chat_rules", category="Nope")[0] == 404
    assert d(w, "chat_rules", reset="1")[1]["rules"]["say"] == "off"


def test_spoken_chat_drops_blocked_lines_and_reads_links_as_link(qapp, window):
    w = window
    d(w, "chat_rules", tts="everyone", cooldown="0", user_cooldown="0",
      blocked="badword, worse thing", max_length="40")
    st, body = d(w, "chat", user="Ann", message="look at https://evil.example/x now")
    assert body["handled"] and w.said == ["Ann says look at link now"]
    st, body = d(w, "chat", user="Ann", message="you BADWORD")
    assert not body["handled"] and body["reason"] == "blocked word" and len(w.said) == 1
    d(w, "chat", user="Ann", message="a" * 100)
    assert w.said[-1] == "Ann says " + "a" * 40
    d(w, "chat_rules", on="0")
    assert d(w, "chat", user="Ann", message="!sound boom")[1]["reason"] == "chat commands are off"


def test_a_reply_posted_as_the_streamer_never_echoes_blocked_words_or_links(qapp, window):
    """"No such sound" replies come from the streamer's own Twitch account: what the
    viewer typed goes through the same filter as spoken chat, and a miss counts for
    the cooldown, so one viewer can't make the account post anything, over and over."""
    w = window
    d(w, "chat_rules", cooldown="0", user_cooldown="30", blocked="badword")
    body = d(w, "chat", user="Ann", message="!sound badword here")[1]
    assert body["reason"] == "blocked word" and not body.get("reply")
    body = d(w, "chat", user="Bo", message="!sound go to https://evil.example/x")[1]
    assert "evil.example" not in body["reply"] and "link" in body["reply"]
    assert d(w, "chat", user="Bo", message="!sound again")[1]["reason"] == "cooldown"
    d(w, "chat_rules", tts="everyone", user_cooldown="0")
    body = d(w, "chat", user="badword_fan", message="hello")[1]   # (whole words only)
    assert body["handled"]
    body = d(w, "chat", user="badword", message="hello")[1]       # the name is read out too
    assert body["reason"] == "blocked word"


def test_alerts_pick_the_rule_for_the_amount_and_play_each_event_once(qapp, window):
    w = window
    assert d(w, "event", type="follow", user="Ann")[1]["handled"] is False   # nothing set
    assert d(w, "alerts", type="donation", sound="boom")[0] == 200
    st, body = d(w, "alerts", type="tip", min="10", sound="Airhorn",
                 say="Thanks {user} for {amount} {currency}: {message}")
    assert st == 200 and [r["min"] for r in body["alerts"]["donation"]] == [0, 10]
    st, body = d(w, "event", type="Donation", user="Ann", amount="$5.00")
    assert body["handled"] and body["name"] == "Boom" and not w.said
    st, body = d(w, "event", type="kofi", user="Bo", amount="25", currency="EUR",
                 message="go www.spam.example now", id="t-1")
    assert body["name"] == "Airhorn" and w.said == ["Thanks Bo for 25 EUR: go link now"]
    st, body = d(w, "event", type="donation", user="Bo", amount="25", id="t-1")   # resent
    assert not body["handled"] and "twice" in body["reason"] and len(w.said) == 1
    left = d(w, "alerts", type="donation", min="10", clear="1")[1]["alerts"]["donation"]
    assert [r["min"] for r in left] == [0]
    assert d(w, "alerts", on="0")[1]["on"] is False
    assert d(w, "event", type="donation", amount="1")[1]["reason"] == "alerts are off"
    # what the request says itself plays even with the alerts off
    st, body = d(w, "event", type="raid", user="Cy", amount="40", sound="airhorn")
    assert body["handled"] and body["name"] == "Airhorn" and body["event"]["amount"] == 40
    assert d(w, "event")[0] == 400
    # a type alone reads its rules back (nothing set is an empty list, not an error)
    st, body = d(w, "alerts", type="tip")
    assert st == 200 and body["type"] == "donation" and [r["min"] for r in body["rules"]] == [0]
    st, body = d(w, "alerts", type="follow")
    assert st == 200 and body["rules"] == [] and "follow" not in body["alerts"]
    assert d(w, "alerts", type="follow", say="")[0] == 400   # a rule that does nothing
    assert d(w, "alerts", type="follow", sound="nope")[0] == 404


def test_each_channel_point_reward_can_play_its_own_sound(qapp, window):
    w = window
    assert d(w, "alerts", type="redeem", sound="boom")[0] == 200                 # any reward
    st, body = d(w, "alerts", type="channel_points", reward="  Honk  the horn ", sound="Airhorn")
    assert st == 200
    assert [(r["min"], r.get("reward")) for r in body["alerts"]["redeem"]] == [
        (0, None), (0, "Honk the horn")]
    assert d(w, "event", type="redeem", reward="honk THE horn")[1]["name"] == "Airhorn"
    assert d(w, "event", type="redeem", reward="Hydrate")[1]["name"] == "Boom"
    # Twitch's own message for it
    body = {"subscription": {"type": "channel.channel_points_custom_reward_redemption.add"},
            "event": {"id": "r-1", "user_name": "Ann", "reward": {"title": "Honk the horn"}}}
    assert d(w, "event", _body=body)[1]["name"] == "Airhorn"
    # changing / clearing one reward's rule leaves the others alone
    d(w, "alerts", type="redeem", reward="Honk the horn", sound="boom")
    assert [r["sound"] for r in streamapi.alert_rules(w)["redeem"]] == ["boom", "boom"]
    left = d(w, "alerts", type="redeem", reward="Honk the horn", clear="1")[1]["alerts"]["redeem"]
    assert left == [{"min": 0, "sound": "boom"}]
    # reward= means nothing for other types
    d(w, "alerts", type="follow", reward="x", sound="boom")
    assert "reward" not in streamapi.alert_rules(w)["follow"][0]


def test_test_alerts_fill_in_a_viewer(qapp, window):
    w = window
    d(w, "alerts", type="sub", say="{user} subbed for {months} months")
    st, body = d(w, "event", type="subscriber", test="1")
    assert body["handled"] and w.said == ["TestViewer subbed for 3 months"]
    # test=1 without a type: a test follow, not an error
    d(w, "alerts", type="follow", say="Thanks for the follow, {user}")
    st, body = d(w, "event", test="1")
    assert st == 200 and body["event"]["type"] == "follow" and body["handled"]
    assert w.said[-1] == "Thanks for the follow, TestViewer"


def test_the_json_other_tools_send_is_read(qapp):
    n = streamapi.normalize
    eventsub = {"subscription": {"type": "channel.cheer"},
                "metadata": {"message_id": "m1"},
                "event": {"user_name": "Ann", "bits": 500, "message": "cheer500 hi"}}
    ev = n({"_body": eventsub})
    assert (ev["type"], ev["user"], ev["amount"], ev["message"], ev["id"]) == \
        ("cheer", "Ann", 500.0, "cheer500 hi", "m1")
    redeem = {"subscription": {"type": "channel.channel_points_custom_reward_redemption.add"},
              "event": {"id": "r1", "user_name": "Bo", "user_input": "say this",
                        "reward": {"title": "Hydrate"}}}
    ev = n({"_body": redeem})
    assert (ev["type"], ev["reward"], ev["message"]) == ("redeem", "Hydrate", "say this")
    labs = {"type": "donation", "message": [{"name": "Cy", "amount": "12.50",
                                             "currency": "USD", "message": "gg", "_id": "x"}]}
    ev = n({"_body": labs})
    assert (ev["type"], ev["user"], ev["amount"], ev["id"]) == ("donation", "Cy", 12.5, "x")
    se = {"listener": "tip-latest", "event": {"name": "Di", "amount": 3, "message": "hey"}}
    assert n({"_body": se})["type"] == "donation" and n({"_body": se})["user"] == "Di"
    kofi = json.dumps({"type": "Donation", "from_name": "Ed", "amount": "3.00",
                       "currency": "GBP", "message": "tea", "kofi_transaction_id": "k9"})
    ev = n({"data": kofi})
    assert (ev["type"], ev["user"], ev["amount"], ev["id"]) == ("donation", "Ed", 3.0, "k9")
    tiktok = n({"type": "gift", "nickname": "Fay", "giftName": "Rose", "repeatCount": "5"})
    assert (tiktok["user"], tiktok["reward"], tiktok["count"]) == ("Fay", "Rose", 5)
    assert n({"type": "x" * 100})["type"] == ""
    assert streamapi.canonical("Channel.Follow") == "follow"
    assert streamapi.canonical("hydrate") == "hydrate"


def test_the_feed_lists_what_chat_and_alerts_did(qapp, window):
    w = window
    d(w, "chat", user="Ann", message="!sound boom")
    d(w, "event", type="follow", user="Bo", sound="airhorn")
    st, body = d(w, "feed")
    assert [(e["kind"], e["user"]) for e in body["events"]] == [("chat", "Ann"), ("alert", "Bo")]
    assert body["events"][1]["type"] == "follow" and body["events"][1]["name"] == "Airhorn"
    first = body["events"][0]["id"]
    assert [e["user"] for e in d(w, "feed", since=str(first))[1]["events"]] == ["Bo"]


def test_a_voice_for_some_seconds_goes_back_after(qapp, window):
    w = window
    d(w, "voice", name="Robot")
    st, body = d(w, "voice", name="chipmunk", seconds="0.05")
    assert st == 200 and body["voice_name"] == "Chipmunk" and body["for_seconds"] == 0.05
    assert process_events(qapp, lambda: w.voice.fx.preset == "Robot")
    assert w.voice.fx.btn_power.isChecked()
    d(w, "voice", on="0")
    d(w, "voice", random="1", seconds="0.05")
    assert w.voice.fx.btn_power.isChecked()
    assert process_events(qapp, lambda: not w.voice.fx.btn_power.isChecked())
    st, body = d(w, "voice", random="1")
    assert st == 200 and body["voice"]
    assert d(w, "voice", name="Robot", seconds="soon")[0] == 400


def test_newer_features_endpoints(qapp, window):
    w = window
    st, sounds = d(w, "sounds", q="HORN")
    assert st == 200 and [s["name"] for s in sounds] == ["Airhorn"]
    assert {"volume", "loop", "press", "plays", "duration", "effects"} <= set(sounds[0])
    assert d(w, "sounds", category="Nope")[0] == 404

    w.cfg.hotkeys_off_hotkey = ""
    assert d(w, "hotkeys", on="0") == (200, {"hotkeys": False})
    w.hkctl.register_hotkeys()                     # (a settings change re-registers)
    assert w.hkctl.hotkeys_on is False             # still off: the API turns them back on
    assert d(w, "hotkeys") == (200, {"hotkeys": True})

    assert d(w, "mic_gate", on="1") == (200, {"mic_gate": True})
    assert w.cfg.mic_gate and w.engine.mic_gate
    assert d(w, "status")[1]["mic_gate"] is True   # a phone shows the switch as it is
    assert d(w, "mic_gate", on="0")[1] == {"mic_gate": False} and not w.engine.mic_gate

    st, body = d(w, "setups")
    assert st == 200 and isinstance(body["setups"], list) and body["on"]["sounds"] == ""
    assert d(w, "setup", name="No such setup")[0] == 404
    assert d(w, "setup", name="", tab="kitchen")[0] == 400 and d(w, "setup")[0] == 400
    assert d(w, "setup", name="")[1]["on"]["sounds"] == ""

    if remote._apps_tab(w) is None:
        assert d(w, "apps") == (409, remote.APPS_OFF)
    else:
        assert d(w, "app")[0] == 400 and d(w, "app", name="nothing.exe")[0] == 404


def test_help_lists_the_new_endpoints(qapp, window):
    eps = d(window, "help")[1]["endpoints"]
    for a in ("chat", "chat_rules", "event", "alerts", "feed", "apps", "app", "hotkeys",
              "mic_gate"):
        assert f"/api/{a}" in eps
    assert "/api/event" in remote.setup_prompt(window.cfg, 7474)


# --------------------------------------------------------------------------- over HTTP

def post(qapp, ctl, path, body: bytes, kind="application/json"):
    out = {}

    def run():
        c = http.client.HTTPConnection(remote.HOST, ctl.port, timeout=5)
        c.request("POST", path, body=body, headers={"X-Token": TOKEN, "Content-Type": kind})
        r = c.getresponse()
        out["status"], out["body"] = r.status, json.loads(r.read() or b"null")
        c.close()
    t = threading.Thread(target=run)
    t.start()
    assert process_events(qapp, lambda: not t.is_alive())
    return out["status"], out["body"]


def test_a_post_body_is_read_as_the_values(qapp):
    calls = []

    def dispatch(action, params):
        calls.append(params)
        return 200, {"ok": action}
    ctl = remote.RemoteControl(dispatch)
    assert ctl.start(0, TOKEN)
    try:
        st, _ = post(qapp, ctl, "/api/event?user=Url",
                     json.dumps({"type": "follow", "user": "Body", "live": True,
                                 "event": {"x": 1}, "token": "nope"}).encode())
        p = calls[-1]
        assert st == 200 and p["type"] == "follow" and p["user"] == "Url"   # the URL wins
        assert p["live"] == "1" and p["_body"]["event"] == {"x": 1} and "token" not in p
        post(qapp, ctl, "/api/chat", b"user=Ann&message=%21sound+boom",
             "application/x-www-form-urlencoded")
        assert calls[-1] == {"user": "Ann", "message": "!sound boom"}
        post(qapp, ctl, "/api/chat", b"not json")
        assert calls[-1] == {}
        st, body = post(qapp, ctl, "/api/chat", b"x" * (remote.BODY_MAX + 1))
        assert st == 413 and len(calls) == 3
    finally:
        ctl.stop()


def test_a_raid_sent_with_an_amount_fills_in_its_count(qapp, window):
    w = window
    assert d(w, "alerts", type="raid", say="{user} raided with {count} people")[0] == 200
    st, body = d(w, "event", type="raid", user="Raider", amount="42")
    assert body["handled"] and body["saying"] == "Raider raided with 42 people", body
    assert streamapi.normalize({"type": "raid", "count": "7", "amount": "42"})["count"] == 7


def test_a_field_with_no_value_is_left_out_not_read_out(qapp, window):
    w = window
    assert d(w, "alerts", type="donation", say="{user} tipped {amount} {currency}")[0] == 200
    st, body = d(w, "event", type="donation", user="Ana", currency="NZD")
    assert body["handled"] and body["saying"] == "Ana tipped NZD", body
    # a name it doesn't know stays as it was written
    assert streamapi.fill("{user} {nope} {amount}", {"user": "Bo", "amount": None}) == "Bo {nope} "
