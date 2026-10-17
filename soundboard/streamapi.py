"""The control API's streamer endpoints (soundboard.remote hands them over): chat
commands, alerts (follows, subs, bits, raids, donations, channel points, TikTok gifts…)
and a feed of what they did.

Onion Board never connects to Twitch, YouTube, Kick, TikTok or a donation site itself:
the streamer's own bot or alert tool (Streamer.bot, Firebot, Mix It Up, SAMMI, TikFinity,
Touch Portal…) already gets those events, and sends them here like any other request
to 127.0.0.1.

    /api/chat?user=…&message=…[&mod=1&sub=1&vip=1&broadcaster=1]
        one chat line. Lines starting with the prefix (!) are commands: !sound <name>,
        !sounds, !random [category], !say <text>, !voice <name>, !stop. Who may use each,
        the cooldowns, a category chat is limited to, blocked words and links:
        /api/chat_rules. Answers `reply`, a line for the bot to post back ("" for none).
    /api/event?type=follow&user=…[&amount=…&message=…&reward=…]
        an alert: does what /api/alerts set for that type (a sound, a random one from a
        category, a line said in the computer voice, a voice for some seconds), or
        what the request itself says (&sound= / &category= / &say= / &voice=). A POST's
        JSON body may instead be what Twitch EventSub, StreamElements, Streamlabs or
        Ko-fi send: it is read as the same thing.
    /api/feed?since=…   what chat and alerts did, newest last (for an overlay or a bot)

Rules live in Config.api_stream; the cooldowns, the feed and the event ids already seen
are kept in memory only. Viewer text is never logged.
"""
from __future__ import annotations

import collections
import difflib
import itertools
import json
import re
import time
import weakref
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from soundboard import usage

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

STREAM_ACTIONS = ("chat", "chat_rules", "event", "alerts", "feed")
FEED_MAX = 200          # entries the feed keeps
SEEN_MAX = 500          # event ids remembered, so an alert sent twice plays once
REPLY_MAX = 450         # characters in a reply (Twitch takes 500 a message)
TEXT_MAX = 500          # characters any viewer text is cut to before anything else
VOICE_S_MAX = 600       # the longest a voice may be put on for

# who may: each is also everyone above it (a mod may do what subs may)
ROLES = ("everyone", "subs", "vips", "mods", "broadcaster", "off")
COMMANDS = ("sound", "sounds", "random", "say", "voice", "stop")
CHAT_DEFAULTS: dict[str, object] = {
    "on": True,
    "prefix": "!",
    # who may use each command
    "sound": "everyone", "sounds": "everyone", "random": "everyone",
    "say": "off", "voice": "mods", "stop": "mods",
    "tts": "off",                     # read every chat line (not a command) aloud
    "tts_format": "{user} says {message}",
    "user_cooldown": 30.0,            # seconds between one viewer's commands
    "cooldown": 5.0,                  # seconds between anyone's commands
    "voice_seconds": 30.0,            # how long !voice keeps a voice on (0: until changed)
    "max_length": 200,                # characters of a viewer's text spoken
    "category": "",                   # chat may only play sounds in this category
    "blocked": [],                    # a line with one of these words does nothing
    "links": False,                   # links in spoken text are read (else "link")
    "reply_list": "Sounds: {list}",
    "reply_missing": "@{user} there's no sound called {name}. Try {prefix}sounds",
}
NUMBERS = {"user_cooldown": (0, 3600), "cooldown": (0, 3600), "voice_seconds": (0, VOICE_S_MAX),
           "max_length": (1, TEXT_MAX)}

# the canonical alert types, and what other tools call them
TYPES = ("follow", "sub", "resub", "gift_sub", "cheer", "raid", "donation", "redeem",
         "gift", "like", "share", "hype_train")
ALIASES = {
    "follower": "follow", "new_follower": "follow", "channel.follow": "follow",
    "subscriber": "sub", "subscription": "sub", "subscribe": "sub",
    "new_subscriber": "sub", "channel.subscribe": "sub", "member": "sub",
    "membership": "sub", "new_member": "sub",
    "resubscribe": "resub", "re_sub": "resub", "channel.subscription.message": "resub",
    "subgift": "gift_sub", "giftsub": "gift_sub", "sub_gift": "gift_sub",
    "gifted_sub": "gift_sub", "community_gift": "gift_sub", "mysterygift": "gift_sub",
    "gifted_membership": "gift_sub", "channel.subscription.gift": "gift_sub",
    "bits": "cheer", "cheers": "cheer", "channel.cheer": "cheer",
    "raided": "raid", "host": "raid", "channel.raid": "raid",
    "tip": "donation", "donate": "donation", "kofi": "donation", "ko-fi": "donation",
    "superchat": "donation", "super_chat": "donation", "charity": "donation",
    "shop_order": "donation", "commission": "donation",
    "redemption": "redeem", "reward": "redeem", "channel_points": "redeem",
    "channelpoints": "redeem", "channel.channel_points_custom_reward_redemption.add": "redeem",
    "tiktok_gift": "gift", "giftsent": "gift",
    "likes": "like", "hypetrain": "hype_train", "channel.hype_train.begin": "hype_train",
}
RULE_KEYS = ("sound", "category", "say", "voice", "voice_seconds", "min", "on")
FIELDS = ("user", "amount", "currency", "message", "reward", "tier", "months", "count",
          "type", "platform")
TEST_EVENT = {"user": "TestViewer", "amount": 5.0, "currency": "USD",
              "message": "This is a test", "reward": "Test reward", "tier": "1000",
              "months": 3, "count": 5}

_LINK = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|tv|gg|io|ly|me|co|xyz)"
                   r"(?:/\S*)?\b")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_FIELD = re.compile(r"\{(\w+)\}")
_TYPE_NAME = re.compile(r"[a-z0-9_.:-]{1,64}")


class _State:
    """What isn't saved: cooldowns, the feed, the event ids already seen."""

    def __init__(self):
        self.user_last: dict[str, float] = {}
        self.last = 0.0
        self.feed: collections.deque = collections.deque(maxlen=FEED_MAX)
        self.ids = itertools.count(1)
        self.seen: collections.OrderedDict = collections.OrderedDict()
        self.voice_turn: tuple | None = None   # the timed voice on now (its turn back is this one)


_states: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def state(mw: MainWindow) -> _State:
    s = _states.get(mw)
    if s is None:
        s = _states[mw] = _State()
    return s


# --------------------------------------------------------------------------- settings

def _stream(mw: MainWindow) -> dict:
    d = mw.cfg.api_stream
    if not isinstance(d, dict):
        d = mw.cfg.api_stream = {}
    return d


def chat_rules(mw: MainWindow) -> dict:
    """The chat rules: the defaults, with what was set over them."""
    saved = _stream(mw).get("chat")
    out = dict(CHAT_DEFAULTS)
    if isinstance(saved, dict):
        for k, v in saved.items():
            if k in CHAT_DEFAULTS and isinstance(v, type(CHAT_DEFAULTS[k])) or (
                    k in NUMBERS and isinstance(v, (int, float)) and not isinstance(v, bool)):
                out[k] = v
    return out


def _truthy(v: str) -> bool | None:
    v = v.strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return None


def _number(v: str, lo: float, hi: float) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return None if n != n else min(max(n, lo), hi)   # (nan != nan)


def set_chat_rules(mw: MainWindow, params: dict) -> tuple[int, object]:
    from soundboard import remote
    if (params.get("reset") or "").strip() not in ("", "0"):
        _stream(mw).pop("chat", None)
        mw._save_later()
        return 200, chat_rules_answer(mw)
    given = {k: v for k, v in params.items() if k in CHAT_DEFAULTS and isinstance(v, str)}
    if not given:
        return 200, chat_rules_answer(mw)
    new = {}
    for k, v in given.items():
        want = CHAT_DEFAULTS[k]
        if k in COMMANDS or k == "tts":
            role = v.strip().lower()
            role = {"all": "everyone", "sub": "subs", "subscribers": "subs", "vip": "vips",
                    "mod": "mods", "moderators": "mods", "streamer": "broadcaster",
                    "none": "off"}.get(role, role)
            if role not in ROLES:
                return 400, {"error": f"{k}= takes one of {', '.join(ROLES)}"}
            new[k] = role
        elif isinstance(want, bool):
            b = _truthy(v)
            if b is None:
                return 400, {"error": f"{k}= takes 1 or 0"}
            new[k] = b
        elif k in NUMBERS:
            n = _number(v, *NUMBERS[k])
            if n is None:
                return 400, {"error": f"{k}= takes a number, {NUMBERS[k][0]} to {NUMBERS[k][1]}"}
            new[k] = int(n) if isinstance(want, int) else n
        elif k == "blocked":
            new[k] = [w.strip().casefold() for w in v.split(",") if w.strip()][:200]
        elif k == "category":
            name = v.strip()
            match = remote.find_category(mw.cfg, name) if name else ""
            if match is None:
                return 404, {"error": f"no category called {name!r}",
                             "categories": list(mw.cfg.categories)}
            new[k] = match
        elif k == "prefix":
            p = v.strip()
            if not 1 <= len(p) <= 3:
                return 400, {"error": "prefix= takes 1 to 3 characters, like !"}
            new[k] = p
        else:   # the reply / spoken formats
            new[k] = _CONTROL.sub("", v)[:REPLY_MAX]
    saved = _stream(mw).setdefault("chat", {})
    if not isinstance(saved, dict):
        saved = _stream(mw)["chat"] = {}
    saved.update(new)
    mw._save_later()
    return 200, chat_rules_answer(mw)


def chat_rules_answer(mw: MainWindow) -> dict:
    return {"rules": chat_rules(mw), "roles": list(ROLES), "commands": list(COMMANDS)}


def alert_rules(mw: MainWindow) -> dict[str, list[dict]]:
    saved = _stream(mw).get("alerts")
    out: dict[str, list[dict]] = {}
    if isinstance(saved, dict):
        for t, rules in saved.items():
            if isinstance(t, str) and isinstance(rules, list):
                good = [r for r in rules if isinstance(r, dict)]
                if good:
                    out[t] = good
    return out


def alerts_on(mw: MainWindow) -> bool:
    return _stream(mw).get("alerts_on", True) is not False


def alerts_answer(mw: MainWindow) -> dict:
    return {"on": alerts_on(mw), "alerts": alert_rules(mw), "types": list(TYPES),
            "fields": list(FIELDS)}


def set_alerts(mw: MainWindow, params: dict) -> tuple[int, object]:
    from soundboard import remote
    kind = canonical(params.get("type") or "")
    if not kind:
        if "type" in params:
            return 400, {"error": "type= takes a name like follow, sub, cheer, raid, donation"}
        if "on" in params:
            on = remote.on_value(params, alerts_on(mw))
            if on is None:
                return 400, remote.BAD_ON
            _stream(mw)["alerts_on"] = on
            mw._save_later()
        return 200, alerts_answer(mw)
    rules = alert_rules(mw)
    have = rules.get(kind, [])
    low = _number(params.get("min") or "0", 0, 1e9) or 0.0
    if (params.get("clear") or "").strip() not in ("", "0"):
        rules[kind] = ([r for r in have if float(r.get("min") or 0) != low]
                       if "min" in params else [])
        if not rules[kind]:
            rules.pop(kind)
        _stream(mw)["alerts"] = rules
        mw._save_later()
        return 200, alerts_answer(mw)
    rule = next((r for r in have if float(r.get("min") or 0) == low), None)
    rule = dict(rule) if rule is not None else {"min": low}
    err = _rule_from(mw, params, rule)
    if err:
        return err
    if not any(rule.get(k) for k in ("sound", "category", "say", "voice")):
        return 400, {"error": "say what it does: &sound=… / &category=… / &say=… / &voice=…"}
    rules[kind] = sorted([r for r in have if float(r.get("min") or 0) != low] + [rule],
                         key=lambda r: float(r.get("min") or 0))
    _stream(mw)["alerts"] = rules
    mw._save_later()
    return 200, alerts_answer(mw)


def _rule_from(mw: MainWindow, params: dict, rule: dict) -> tuple[int, object] | None:
    """Fill `rule` from params' sound / category / say / voice / voice_seconds / on,
    each checked. An error answer, or None."""
    from soundboard import remote
    if "sound" in params:
        name = params["sound"].strip()
        if name and _sound_named(mw, name) is None:
            return remote.no_sound(mw.cfg, {"name": name})
        rule["sound"] = name
    if "category" in params:
        name = params["category"].strip()
        if name in ("", "*", "all", "any"):
            rule["category"] = "*" if name else ""
        else:
            match = remote.find_category(mw.cfg, name)
            if match is None:
                return 404, {"error": f"no category called {name!r}",
                             "categories": list(mw.cfg.categories)}
            rule["category"] = match
    if "say" in params:
        rule["say"] = _CONTROL.sub("", params["say"])[:TEXT_MAX]
    if "voice" in params:
        name = params["voice"].strip()
        if name:
            if not mw.tabctl.tab_on("voice"):
                return 409, remote.VOICE_OFF
            match = _voice_named(mw, name)
            if match is None:
                return 404, {"error": f"no voice called {name!r}",
                             "voices": remote.voice_names(mw)}
            name = match
        rule["voice"] = name
    if "voice_seconds" in params:
        n = _number(params["voice_seconds"], 0, VOICE_S_MAX)
        if n is None:
            return 400, {"error": f"voice_seconds= takes a number, 0 to {VOICE_S_MAX}"}
        rule["voice_seconds"] = n
    if "on" in params and "type" in params:
        b = _truthy(params["on"])
        if b is None:
            return 400, remote.BAD_ON
        rule["on"] = b
    return None


# --------------------------------------------------------------------------- doing things

def _sound_named(mw: MainWindow, name: str, pool=None):
    """A sound by exact name (any case), else the one sound whose name starts with or
    holds `name`; None if none (or several) do."""
    want = name.strip().casefold()
    if not want:
        return None
    sounds = list(mw.cfg.sounds if pool is None else pool)
    exact = next((m for m in sounds if m.name.casefold() == want), None)
    if exact is not None:
        return exact
    for test in (lambda n: n.startswith(want), lambda n: want in n):
        hits = [m for m in sounds if test(m.name.casefold())]
        if hits:
            return hits[0] if len(hits) == 1 else None   # several: say which
    return None


def _voice_named(mw: MainWindow, name: str) -> str | None:
    from soundboard import remote, voicefx
    want = name.strip().casefold()
    names = remote.voice_names(mw)
    return next((n for n in names if want in (n.casefold(), voicefx.shown(n).casefold())),
                None)


def clean_text(text: str, rules: dict) -> str | None:
    """A viewer's text, made safe to speak: no control characters, links read as "link"
    (unless allowed), cut to max_length. None when it has a blocked word."""
    text = " ".join(_CONTROL.sub(" ", str(text)[:TEXT_MAX * 2]).split())
    folded = text.casefold()
    for word in rules.get("blocked") or []:
        if word and re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", folded):
            return None
    if not rules.get("links"):
        text = _LINK.sub("link", text)
    return text[:int(rules.get("max_length") or TEXT_MAX)]


def fill(template: str, values: dict) -> str:
    """{user}, {amount}… in `template` from `values` (unknown ones are left as they are)."""
    def one(m):
        v = values.get(m.group(1))
        if v is None:
            return m.group(0)
        if isinstance(v, float):
            return f"{v:g}"
        return str(v)
    return _FIELD.sub(one, template)


def _play(mw: MainWindow, m) -> tuple[int, dict]:
    if m.id not in mw.audio:
        return 409, {"error": "that sound hasn't loaded (yet)"}
    mw.playctl.play(m.id)
    return 200, {"playing": m.id, "name": m.name}


def _say(mw: MainWindow, text: str) -> tuple[int, dict]:
    from soundboard import remote
    if not mw.tabctl.tab_on("voice"):
        return 409, remote.VOICE_OFF
    remote._voice_tab(mw).speech.say_line(text)
    return 200, {"saying": text}


def voice_for(mw: MainWindow, name: str, seconds: float) -> dict:
    """Turn the voice changer on with `name`; after `seconds` (0: never) put back what
    was on before, unless something else changed the voice meanwhile."""
    from soundboard import remote
    fx = remote._voice_tab(mw).fx
    st = state(mw)
    was_on, was = fx.btn_power.isChecked(), fx.preset
    if st.voice_turn is not None:   # a timed voice is on: go back to what was before it
        was_on, was = st.voice_turn[1], st.voice_turn[2]
    fx.pick(name)
    if seconds <= 0:
        st.voice_turn = None
        return remote.voice_state(mw)
    turn = (object(), was_on, was, name)
    st.voice_turn = turn

    def back():
        if st.voice_turn is not turn or not mw.tabctl.tab_on("voice"):
            return
        st.voice_turn = None
        f = remote._voice_tab(mw).fx
        if f.preset != name or not f.btn_power.isChecked():
            return   # changed by hand meanwhile: leave it
        if was_on and was:
            f.pick(was)
        else:
            mw.hkctl._set_voice(False)
    QTimer.singleShot(int(seconds * 1000), mw, back)
    return {**remote.voice_state(mw), "for_seconds": seconds}


def _log(mw: MainWindow, kind: str, **info) -> int:
    st = state(mw)
    n = next(st.ids)
    st.feed.append({"id": n, "time": round(time.time(), 3), "kind": kind, **info})
    if kind == "chat":   # the names only (usage.py): never who, what or how much
        usage.used("api-chat-command")
    elif kind == "alert":
        donation = info.get("type") == "donation"
        usage.used("api-alert-donation" if donation else "api-alert")
    return n


def feed(mw: MainWindow, params: dict) -> tuple[int, object]:
    st = state(mw)
    since = _number(params.get("since") or "0", 0, 1e15) or 0
    limit = int(_number(params.get("limit") or str(FEED_MAX), 1, FEED_MAX) or FEED_MAX)
    items = [e for e in st.feed if e["id"] > since][-limit:]
    last = st.feed[-1]["id"] if st.feed else 0
    return 200, {"events": items, "last": last}


# --------------------------------------------------------------------------- chat

def _rank(params: dict) -> int:
    """The chatter's place in ROLES: 0 everyone … 4 broadcaster."""
    def flag(*keys):
        return any(_truthy(str(params.get(k) or "")) for k in keys)
    badges = str(params.get("badges") or "").lower()
    role = str(params.get("role") or "").strip().lower()
    if flag("broadcaster", "is_broadcaster", "isbroadcaster", "owner") or "broadcaster" in badges \
            or role in ("broadcaster", "streamer", "owner"):
        return 4
    if flag("mod", "moderator", "is_mod", "ismod", "ismoderator") or "moderator" in badges \
            or role in ("mod", "mods", "moderator"):
        return 3
    if flag("vip", "is_vip", "isvip") or "vip" in badges or role in ("vip", "vips"):
        return 2
    if flag("sub", "subscriber", "is_sub", "issub", "issubscriber", "member") \
            or "subscriber" in badges or "founder" in badges \
            or role in ("sub", "subs", "subscriber", "member"):
        return 1
    return 0


def _allowed(rules: dict, what: str, rank: int) -> bool:
    need = rules.get(what, "off")
    return need in ROLES and need != "off" and rank >= ROLES.index(need)


def chat(mw: MainWindow, params: dict) -> tuple[int, object]:
    """One chat line: a command, or (with tts on) read out."""
    from soundboard import remote
    rules = chat_rules(mw)
    user = " ".join(str(params.get("user") or params.get("username") or params.get("name")
                        or "someone").split())[:40] or "someone"
    raw = params.get("message") or params.get("msg") or params.get("text") or ""
    if not isinstance(raw, str) or not raw.strip():
        return 400, {"error": "say what they wrote: ?user=…&message=…"}
    if not rules["on"]:
        return 200, {"handled": False, "reason": "chat commands are off", "reply": ""}
    rank = _rank(params)
    line = " ".join(raw.split())[:TEXT_MAX]
    prefix = str(rules["prefix"])
    out = {"handled": False, "user": user, "reply": ""}
    if not line.startswith(prefix):
        if not _allowed(rules, "tts", rank):
            return 200, {**out, "reason": "not a command"}
        text = clean_text(line, rules)
        if text is None:
            return 200, {**out, "reason": "blocked word"}
        wait = _cooldown(mw, rules, user, rank)
        if wait:
            return 200, {**out, "reason": "cooldown", "wait": wait}
        status, body = _say(mw, fill(str(rules["tts_format"]), {"user": user, "message": text}))
        if status != 200:
            return 200, {**out, "reason": body.get("error", "")}
        _used(mw, user)
        _log(mw, "chat", user=user, command="tts", text=text)
        return 200, {**out, "handled": True, "command": "tts"}
    word, _, rest = line[len(prefix):].partition(" ")
    cmd = word.strip().lower()
    rest = rest.strip()
    if cmd not in COMMANDS:
        return 200, {**out, "reason": "not one of Onion Board's commands"}
    out["command"] = cmd
    if not _allowed(rules, cmd, rank):
        return 200, {**out, "reason": "not allowed"}
    pool = _chat_pool(mw, rules)
    if cmd == "sounds":
        names = [m.name for m in pool]
        text = ", ".join(names)
        if len(text) > REPLY_MAX - 40:
            cut = text[:REPLY_MAX - 40].rsplit(", ", 1)[0]
            text = f"{cut} … (+{len(names) - cut.count(', ') - 1} more)"
        return 200, {**out, "handled": True, "count": len(names),
                     "reply": fill(str(rules["reply_list"]), {"list": text or "(none)",
                                                              "user": user})}
    if cmd == "stop":
        mw.playctl.stop_all()
        _log(mw, "chat", user=user, command="stop")
        return 200, {**out, "handled": True, "stopped": "all"}
    wait = _cooldown(mw, rules, user, rank)
    if wait:
        return 200, {**out, "reason": "cooldown", "wait": wait}
    if cmd == "sound":
        if not rest:
            return 200, {**out, "reason": "no sound named",
                         "reply": f"@{user} {prefix}sound <name> · {prefix}sounds lists them"}
        m = _sound_named(mw, rest, pool)
        if m is None:
            close = difflib.get_close_matches(rest, [s.name for s in pool], 3, 0.5)
            reply = fill(str(rules["reply_missing"]), {"user": user, "name": rest[:60],
                                                      "prefix": prefix})
            if close:
                reply += " (" + ", ".join(close) + "?)"
            return 200, {**out, "reason": "no such sound", "reply": reply[:REPLY_MAX]}
        status, body = _play(mw, m)
    elif cmd == "random":
        cat = rules["category"] or ""
        if rest:
            cat = remote.find_category(mw.cfg, rest)
            if cat is None or (rules["category"] and cat != rules["category"]):
                return 200, {**out, "reason": "no such category"}
        sid = mw.playctl.play_random(cat)
        m = mw.meta(sid) if sid is not None else None
        status, body = ((200, {"playing": sid, "name": m.name}) if m is not None
                        else (404, {"error": "no sound to play there"}))
    elif cmd == "say":
        text = clean_text(rest, rules)
        if not text:
            return 200, {**out, "reason": "blocked word" if text is None else "nothing to say"}
        status, body = _say(mw, text)
    else:   # voice
        if not mw.tabctl.tab_on("voice"):
            return 200, {**out, "reason": remote.VOICE_OFF["error"]}
        name = _voice_named(mw, rest) if rest else None
        if name is None:
            return 200, {**out, "reason": "no such voice", "reply":
                         f"@{user} voices: " + ", ".join(remote.voice_names(mw))[:REPLY_MAX - 40]}
        status, body = 200, voice_for(mw, name, float(rules["voice_seconds"]))
    if status != 200:
        return 200, {**out, "reason": body.get("error", "") if isinstance(body, dict) else ""}
    _used(mw, user)
    _log(mw, "chat", user=user, command=cmd, **{k: v for k, v in body.items()
                                                if k in ("name", "saying", "voice_name")})
    return 200, {**out, "handled": True, **body}


def _chat_pool(mw: MainWindow, rules: dict) -> list:
    cat = rules.get("category") or ""
    return [m for m in mw.cfg.sounds if not cat or cat in m.tags]


def _cooldown(mw: MainWindow, rules: dict, user: str, rank: int) -> float:
    """Seconds left before `user` may use a command again (0: now). Mods and the
    broadcaster don't wait."""
    if rank >= ROLES.index("mods"):
        return 0.0
    st, now = state(mw), time.monotonic()
    left = max(st.last + float(rules["cooldown"]) - now,
               st.user_last.get(user.casefold(), -1e9) + float(rules["user_cooldown"]) - now)
    return round(left, 1) if left > 0 else 0.0


def _used(mw: MainWindow, user: str):
    st, now = state(mw), time.monotonic()
    st.last = now
    st.user_last[user.casefold()] = now
    if len(st.user_last) > 5000:   # a huge chat: forget the ones long done
        st.user_last = {u: t for u, t in st.user_last.items() if now - t < 3600}


# --------------------------------------------------------------------------- alerts

def canonical(kind: str) -> str:
    """An alert type as /api/alerts keeps it: "Channel.Follow", "follower" -> "follow".
    Unknown names stay themselves (a type of one's own, like "hydrate"); "" if unusable."""
    k = kind.strip().lower().replace(" ", "_")
    k = ALIASES.get(k, ALIASES.get(k.replace("-", "_"), k))
    return k if _TYPE_NAME.fullmatch(k) else ""


def _amount(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    s = re.sub(r"[^\d.,-]", "", str(v))
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if len(s.rsplit(",", 1)[1]) != 3 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _meta_id(body: dict):
    meta = body.get("metadata")
    return meta.get("message_id") if isinstance(meta, dict) else None


def normalize(params: dict) -> dict:
    """What happened, from a flat request or from the JSON Twitch EventSub,
    StreamElements, Streamlabs or Ko-fi send: {type, user, amount, …, id}."""
    body = _d(params.get("_body"))
    if isinstance(params.get("data"), str) and params["data"].lstrip().startswith("{"):
        try:   # Ko-fi posts its JSON as a form field called data
            k = json.loads(params["data"])
            if isinstance(k, dict):
                body = {**k, **body}
        except ValueError:
            pass
    flat = {k: v for k, v in {**body, **params}.items()
            if isinstance(v, (str, int, float)) and not isinstance(v, bool)}
    ev: dict = {}
    sub, e, data = _d(body.get("subscription")), _d(body.get("event")), _d(body.get("data"))
    labs = body.get("message")
    first = _d(labs[0]) if isinstance(labs, list) and labs else {}
    if sub and e:   # Twitch EventSub
        msg = e.get("message")
        ev = {"type": sub.get("type"), "platform": "twitch",
              "user": _first(e, "user_name", "from_broadcaster_user_name", "user_login"),
              "amount": _first(e, "bits", "viewers", "total", "cumulative_total"),
              "message": msg.get("text") if isinstance(msg, dict) else msg or e.get("user_input"),
              "reward": _d(e.get("reward")).get("title"),
              "tier": e.get("tier"), "months": e.get("cumulative_months"),
              "id": e.get("id") or _meta_id(body)}
        if ev["type"] == "channel.raid":
            ev["count"] = e.get("viewers")
    elif isinstance(body.get("listener"), str) and e:   # StreamElements widget
        ev = {"type": str(body["listener"]).split("-")[0], "platform": "streamelements",
              "user": _first(e, "name", "displayName", "username"),
              "amount": _first(e, "amount", "count"), "message": e.get("message"),
              "tier": e.get("tier"), "id": e.get("_id")}
    elif first:                                                            # Streamlabs
        m = first
        ev = {"type": body.get("type") or body.get("for"), "platform": "streamlabs",
              "user": _first(m, "name", "from", "display_name"),
              "amount": _first(m, "amount", "raiders", "viewers", "months"),
              "currency": m.get("currency"), "message": m.get("message"),
              "months": m.get("months"), "id": _first(m, "_id", "id", "event_id")}
    elif data and body.get("type"):                                        # StreamElements socket
        d = data
        ev = {"type": body["type"], "platform": "streamelements",
              "user": _first(d, "displayName", "username", "name"),
              "amount": _first(d, "amount", "count", "viewers"), "currency": d.get("currency"),
              "message": d.get("message"), "tier": d.get("tier"),
              "id": _first(body, "_id", "activityId")}
    elif "from_name" in flat and "kofi_transaction_id" in flat:            # Ko-fi
        ev = {"type": flat.get("type") or "donation", "platform": "ko-fi",
              "user": flat.get("from_name"), "amount": flat.get("amount"),
              "currency": flat.get("currency"), "message": flat.get("message"),
              "id": flat.get("kofi_transaction_id")}
    out = {
        "type": _first(ev, "type") or _first(flat, "type", "event", "kind", "alert") or "",
        "user": _first(ev, "user") or _first(flat, "user", "username", "name", "from_name",
                                             "display_name", "displayName", "nickname",
                                             "uniqueId", "sender"),
        "amount": _first(ev, "amount") if _first(ev, "amount") is not None
        else _first(flat, "amount", "bits", "viewers", "count", "value", "coins",
                    "diamonds", "giftCount", "repeatCount", "months"),
        "currency": _first(ev, "currency") or _first(flat, "currency"),
        "message": _first(ev, "message") or _first(flat, "message", "msg", "text", "input",
                                                   "user_input", "comment"),
        "reward": _first(ev, "reward") or _first(flat, "reward", "reward_name", "title",
                                                 "rewardName", "giftName", "gift"),
        "tier": _first(ev, "tier") or _first(flat, "tier", "plan"),
        "months": _first(ev, "months") or _first(flat, "months", "cumulative_months"),
        "count": _first(ev, "count") or _first(flat, "count", "viewers", "giftCount",
                                               "repeatCount"),
        "platform": _first(ev, "platform") or _first(flat, "platform", "source", "service"),
        "id": _first(ev, "id") or _first(flat, "id", "event_id", "eventId", "message_id",
                                         "msgId", "transaction_id"),
    }
    out["type"] = canonical(str(out["type"]))
    out["amount"] = _amount(out["amount"])
    for k in ("user", "currency", "message", "reward", "tier", "platform", "id"):
        out[k] = " ".join(str(out[k]).split())[:TEXT_MAX] if out[k] is not None else ""
    for k in ("months", "count"):
        n = _amount(out[k])
        out[k] = int(n) if n is not None else 0
    return out


def pick_rule(rules: list[dict], amount: float | None) -> dict | None:
    """The rule with the highest `min` the amount reaches (switched-off ones skipped)."""
    a = amount or 0.0
    good = [r for r in rules if r.get("on", True) is not False and float(r.get("min") or 0) <= a]
    return max(good, key=lambda r: float(r.get("min") or 0), default=None)


def event(mw: MainWindow, params: dict) -> tuple[int, object]:
    test = (params.get("test") or "").strip() not in ("", "0")
    ev = normalize(params)
    if not ev["type"]:
        return 400, {"error": "say what happened: ?type=follow / sub / cheer / raid / "
                              "donation / redeem / gift …", "types": list(TYPES)}
    if test:
        ev = {**ev, **{k: v for k, v in TEST_EVENT.items() if not ev.get(k)}, "id": ""}
    st = state(mw)
    if ev["id"]:
        key = f"{ev['type']}:{ev['id']}"
        if key in st.seen:
            return 200, {"handled": False, "reason": "already done (the same id came twice)",
                         "event": ev}
        st.seen[key] = True
        while len(st.seen) > SEEN_MAX:
            st.seen.popitem(last=False)
    inline = {k: params[k] for k in ("sound", "category", "say", "voice", "voice_seconds")
              if isinstance(params.get(k), str)}
    if inline:
        rule: dict = {}
        err = _rule_from(mw, inline, rule)
        if err:
            return err
    else:
        if not alerts_on(mw) and not test:
            return 200, {"handled": False, "reason": "alerts are off", "event": ev}
        found = pick_rule(alert_rules(mw).get(ev["type"], []), ev["amount"])
        if found is None:
            return 200, {"handled": False, "reason": f"nothing is set for {ev['type']} "
                         "(set it with /api/alerts)", "event": ev}
        rule = found
    return _run_rule(mw, rule, ev)


def _run_rule(mw: MainWindow, rule: dict, ev: dict) -> tuple[int, object]:
    from soundboard import remote
    rules = chat_rules(mw)
    msg = clean_text(ev["message"], rules) if ev["message"] else ""
    values = {**ev, "message": msg or "", "user": clean_text(ev["user"], rules) or "someone",
              "reward": clean_text(ev["reward"], rules) or ""}
    did: dict = {}
    problems = []
    if rule.get("sound"):
        m = _sound_named(mw, str(rule["sound"]))
        if m is None:
            problems.append(f"no sound called {rule['sound']!r}")
        else:
            status, body = _play(mw, m)
            if status == 200:
                did.update(body)
            else:
                problems.append(body["error"])
    elif rule.get("category"):
        cat = "" if rule["category"] == "*" else remote.find_category(mw.cfg, str(rule["category"]))
        sid = mw.playctl.play_random(cat) if cat is not None else None
        m = mw.meta(sid) if sid is not None else None
        if m is None:
            problems.append("no sound to play there")
        else:
            did.update(playing=sid, name=m.name)
    if rule.get("voice"):
        if not mw.tabctl.tab_on("voice"):
            problems.append(remote.VOICE_OFF["error"])
        else:
            name = _voice_named(mw, str(rule["voice"]))
            if name is None:
                problems.append(f"no voice called {rule['voice']!r}")
            else:
                v = voice_for(mw, name, float(rule.get("voice_seconds") or 0))
                did.update(voice_name=v["voice_name"])
    if rule.get("say"):
        text = fill(str(rule["say"]), values)   # (a message with a blocked word: "")
        status, body = _say(mw, " ".join(text.split())[:TEXT_MAX])
        if status == 200:
            did.update(body)
        else:
            problems.append(body["error"])
    handled = bool(did)
    if handled:
        _log(mw, "alert", type=ev["type"], user=values["user"], amount=ev["amount"],
             **{k: v for k, v in did.items() if k in ("name", "saying", "voice_name")})
    out = {"handled": handled, "event": ev, **did}
    if problems:
        out["problems"] = problems
    return 200, out


# --------------------------------------------------------------------------- the API

def dispatch(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    if action == "chat":
        return chat(mw, params)
    if action == "chat_rules":
        return set_chat_rules(mw, params)
    if action == "event":
        return event(mw, params)
    if action == "alerts":
        return set_alerts(mw, params)
    return feed(mw, params)
