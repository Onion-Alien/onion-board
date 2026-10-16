"""Anonymous chat (the Chat tab): one room, text only, for everyone using the app.

It talks to the project's own small server (server/store in this repository, the same
Cloudflare Worker as the sound store). Nobody picks a name: the server gives each install
a funny one that changes every day, and keeps only the last few messages in memory. The
app sends a random id it made itself (Config.store_id, shared with the store), which the
server only keeps as a salted hash. Messages are plain text: no links, no pictures. The
tab asks for new messages with a long poll, which waits on the server until something is
said, so it goes through the proxy, Tor and Offline mode like every other feature. Chat
has its own switch in Settings > Privacy & security (FEATURE)."""
from __future__ import annotations

import json
import logging
import secrets
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from soundboard import net, netlog
from soundboard.i18n import _

log = logging.getLogger(__name__)

FEATURE = "chat"          # its switch in Settings > Privacy & security (soundboard.net)
BASE = "https://onion-board-store.onion-alien.workers.dev"
MAX_LEN = 280             # the server's limit on one message
POLL_S = 25               # how long one poll may wait (the server holds it for 20)
LIST_LIMIT = 1 << 18      # 60 short messages are a few KB
KEEP = 200                # messages the tab keeps on screen
RULES_VERSION = 1         # bump to ask everyone to accept the rules again


class ChatError(Exception):
    """What went wrong, in words for the user."""


@dataclass
class Message:
    id: int
    t: int          # milliseconds since 1970
    user: str       # the day's short tag for who said it (for Mute and Report)
    name: str
    text: str


def install_id(cfg) -> str:
    """This install's random id, made the first time it's needed (the store's)."""
    if not getattr(cfg, "store_id", ""):
        cfg.store_id = str(uuid.UUID(bytes=secrets.token_bytes(16), version=4))
    return cfg.store_id


def parse(raw) -> tuple[list[Message], int, bool]:
    """(the messages in an answer, the room's last number, whether chat is off). Odd
    entries are left out."""
    if not isinstance(raw, dict):
        return [], 0, False
    out = []
    for d in raw.get("messages") if isinstance(raw.get("messages"), list) else []:
        try:
            m = Message(id=int(d["id"]), t=int(d.get("t") or 0), user=str(d.get("u") or "")[:16],
                        name=str(d["name"]).strip()[:40], text=str(d["text"]).strip()[:MAX_LEN])
        except (KeyError, TypeError, ValueError):
            continue
        if m.id > 0 and m.name and m.text:
            out.append(m)
    try:
        last = max(0, int(raw.get("last") or 0))
    except (TypeError, ValueError):
        last = 0
    return out, last, bool(raw.get("off"))


def _why(code: int, err: str) -> str:
    if err == "off" or code == 503:
        return _("Chat is switched off for now. Try again later.")
    if err == "slow down" or code == 429:
        return _("Slow down a little.")
    if err == "muted":
        return _("You've been muted for a while after people reported your messages.")
    if err == "banned" or code == 403:
        return _("You can't use chat.")
    if err == "no links":
        return _("No links in chat.")
    if err == "repeat":
        return _("You just said that.")
    if err == "too long":
        return _("That's too long: up to %d characters.") % MAX_LEN
    if err == "not allowed":
        return _("That message isn't allowed here.")
    if err == "empty":
        return _("Type something first.")
    if code == 404:
        return _("That message is gone.")
    return _("Chat had a problem. Try again in a bit.")


def _request(method: str, path: str, install: str, body: bytes | None = None,
             timeout: float = 15) -> bytes:
    """One call to the server; its answer. Raises ChatError (or net.ProxyError when chat
    is switched off or Offline). Call off the UI thread."""
    headers = {"User-Agent": "OnionBoard (chat)", "X-Onion-Install": install}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with net.urlopen(req, timeout=timeout, feature=FEATURE) as r:
            data = r.read(LIST_LIMIT + 1)
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read(4096) or b"{}").get("error", "")
        except (ValueError, AttributeError):
            err = ""
        raise ChatError(_why(e.code, err)) from None
    except net.ProxyError:
        raise
    except OSError as e:
        log.info("chat %s %s failed: %s", method, path, e)
        raise ChatError(_("Couldn't reach chat. Check your internet.")) from None
    if len(data) > LIST_LIMIT:
        raise ChatError(_("Chat sent more than it should, so it was left."))
    return data


def _json(data: bytes):
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        raise ChatError(_("Chat had a problem. Try again in a bit.")) from None


def poll(install: str, after: int, wait: bool = True) -> tuple[list[Message], int, bool]:
    """The messages after number `after` (everything the room has when `after` is 0).
    With `wait` the server holds the call until someone speaks, up to ~20 s. Call off the
    UI thread."""
    if after == 0:
        netlog.cause(FEATURE, "You opened the Chat tab: reading the room")
    else:
        netlog.cause(FEATURE, "You have the Chat tab open: waiting for new messages")
    path = f"/v1/chat?after={max(0, int(after))}" + ("&wait=1" if wait else "")
    return parse(_json(_request("GET", path, install, timeout=POLL_S + 5 if wait else 15)))


def say(install: str, text: str) -> Message:
    """Say something. The message as the room has it. Raises ChatError."""
    text = " ".join(text.split())
    if not text:
        raise ChatError(_why(400, "empty"))
    if len(text) > MAX_LEN:
        raise ChatError(_why(400, "too long"))
    netlog.cause(FEATURE, "You sent a chat message")
    raw = _json(_request("POST", "/v1/chat", install, json.dumps({"text": text}).encode()))
    got, _last, _off = parse({"messages": [raw.get("message")] if isinstance(raw, dict) else []})
    if not got:
        raise ChatError(_why(500, ""))
    return got[0]


def report(install: str, message_id: int) -> None:
    """Tell the server a message breaks the rules."""
    netlog.cause(FEATURE, "You reported a chat message")
    _request("POST", f"/v1/chat/{int(message_id)}/report", install, b"{}")
