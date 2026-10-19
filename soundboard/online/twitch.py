"""Talking to Twitch for Settings → Remote's *Connect Twitch* (soundboard.control.twitchlink
does the live part): signing in with Twitch's device code (the streamer types a short
code on twitch.tv, so their password never comes near the app), keeping the token
fresh, and the few Helix calls the link needs (who signed in, their channel point
rewards, listening for events, a chat reply).

Every call is blocking and goes through soundboard.online.net (feature "twitch": its own
switch in Settings > Privacy & security, Offline mode, the proxy / Tor): run them on
a worker thread, never the UI thread. Tokens are never logged.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from soundboard.online import net

log = logging.getLogger(__name__)

FEATURE = "twitch"
# Onion Board's app on dev.twitch.tv: a public client (no secret; the device code flow
# is made for apps like this). Public by design: every copy of the app carries it.
CLIENT_ID = "hmy51yc60hgmas5swt19ov963s83h3"
AUTH = "https://id.twitch.tv/oauth2"
HELIX = "https://api.twitch.tv/helix"
EVENTSUB_WS = "wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30"
TIMEOUT_S = 15
# what the link asks for, and why (Twitch shows the streamer this list)
SCOPES = (
    "channel:read:redemptions",     # channel point rewards and redemptions
    "bits:read",                    # cheers
    "channel:read:subscriptions",   # subs, resubs, gift subs
    "moderator:read:followers",     # follows
    "user:read:chat",               # chat lines, for chat commands
    "user:write:chat",              # replying to a chat command
)
# the events the link listens for: (type, version, condition keys set to the streamer's id)
SUBSCRIPTIONS = (
    ("channel.channel_points_custom_reward_redemption.add", "1", ("broadcaster_user_id",)),
    ("channel.cheer", "1", ("broadcaster_user_id",)),
    ("channel.follow", "2", ("broadcaster_user_id", "moderator_user_id")),
    ("channel.subscribe", "1", ("broadcaster_user_id",)),
    ("channel.subscription.message", "1", ("broadcaster_user_id",)),
    ("channel.subscription.gift", "1", ("broadcaster_user_id",)),
    ("channel.raid", "1", ("to_broadcaster_user_id",)),
    ("channel.chat.message", "1", ("broadcaster_user_id", "user_id")),
)


class TwitchError(Exception):
    """A call Twitch refused, or one that didn't get there. `status` is Twitch's HTTP
    status (0: no answer), `code` its short reason ("authorization_pending")."""

    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    url: str           # where the streamer types it (twitch.tv/activate…)
    interval: float    # seconds between polls
    expires_in: float


@dataclass
class Tokens:
    access: str
    refresh: str


def offered() -> bool:
    return bool(CLIENT_ID)


def _call(method: str, url: str, *, form: dict | None = None, body: dict | None = None,
          token: str = "", auth: str = "Bearer") -> dict:
    headers = {"Client-Id": CLIENT_ID, "Accept": "application/json"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"{auth} {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with net.urlopen(req, timeout=TIMEOUT_S, feature=FEATURE) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        try:
            info = json.loads(e.read() or b"{}")
        except ValueError:
            info = {}
        msg = str(info.get("message") or info.get("error") or e.reason or e.code)
        raise TwitchError(msg, e.code, msg if " " not in msg else "") from None
    except OSError as e:   # no connection, switched off (net.FeatureOff), the proxy…
        raise TwitchError(str(e)) from None
    try:
        out = json.loads(raw or b"{}")
    except ValueError:
        raise TwitchError("Twitch sent something that isn't JSON") from None
    return out if isinstance(out, dict) else {}


# --------------------------------------------------------------------------- signing in

def start_login() -> DeviceCode:
    d = _call("POST", f"{AUTH}/device", form={"client_id": CLIENT_ID, "scopes": " ".join(SCOPES)})
    try:
        return DeviceCode(str(d["device_code"]), str(d["user_code"]),
                          str(d["verification_uri"]), float(d.get("interval") or 5),
                          float(d.get("expires_in") or 1800))
    except (KeyError, TypeError, ValueError):
        raise TwitchError("Twitch didn't send a code") from None


def finish_login(device_code: str) -> Tokens | None:
    """The tokens once the streamer has said yes on twitch.tv; None while they haven't
    yet. TwitchError when they said no or the code ran out."""
    try:
        d = _call("POST", f"{AUTH}/token", form={
            "client_id": CLIENT_ID, "scopes": " ".join(SCOPES), "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    except TwitchError as e:
        if e.code == "authorization_pending" or str(e) == "authorization_pending":
            return None
        raise
    return _tokens(d)


def refresh(refresh_token: str) -> Tokens:
    """New tokens (a public client's refresh token works once: keep the new one)."""
    d = _call("POST", f"{AUTH}/token", form={
        "client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": refresh_token})
    return _tokens(d)


def _tokens(d: dict) -> Tokens:
    if not d.get("access_token"):
        raise TwitchError("Twitch didn't send a token")
    return Tokens(str(d["access_token"]), str(d.get("refresh_token") or ""))


def validate(token: str) -> dict:
    """{"login", "user_id", "scopes", …} for a token; TwitchError(401) if it's no good."""
    return _call("GET", f"{AUTH}/validate", token=token, auth="OAuth")


def revoke(token: str) -> None:
    """Disconnecting: tell Twitch to forget the token (best effort)."""
    try:
        _call("POST", f"{AUTH}/revoke", form={"client_id": CLIENT_ID, "token": token})
    except TwitchError as e:
        log.info("Twitch didn't take the token back: %s", e)


# --------------------------------------------------------------------------- Helix

def rewards(token: str, user_id: str) -> list[str]:
    """The titles of the streamer's channel point rewards ([] for a channel without
    channel points: Twitch answers 403 until they're an affiliate)."""
    try:
        d = _call("GET", f"{HELIX}/channel_points/custom_rewards?"
                  + urllib.parse.urlencode({"broadcaster_id": user_id}), token=token)
    except TwitchError as e:
        if e.status == 403:
            return []
        raise
    titles = [str(r.get("title") or "").strip() for r in d.get("data") or []
              if isinstance(r, dict)]
    return sorted({t for t in titles if t}, key=str.casefold)


def subscribe(token: str, user_id: str, session_id: str) -> list[str]:
    """Listen for every event in SUBSCRIPTIONS on the EventSub socket `session_id`.
    Returns the types Twitch refused (a channel without channel points can't have
    redemptions); raises only when it refused the token itself."""
    refused = []
    for kind, version, keys in SUBSCRIPTIONS:
        try:
            _call("POST", f"{HELIX}/eventsub/subscriptions", token=token, body={
                "type": kind, "version": version,
                "condition": {k: user_id for k in keys},
                "transport": {"method": "websocket", "session_id": session_id}})
        except TwitchError as e:
            if e.status == 401:
                raise
            log.info("Twitch refused %s: %s", kind, e)
            refused.append(kind)
    return refused


def send_chat(token: str, user_id: str, message: str) -> None:
    _call("POST", f"{HELIX}/chat/messages", token=token, body={
        "broadcaster_id": user_id, "sender_id": user_id, "message": message[:500]})
