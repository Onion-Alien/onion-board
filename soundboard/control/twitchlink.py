"""The live link to Twitch behind Settings → Remote's *Connect Twitch*: signing in (the
device code), then Twitch's EventSub socket, whose events go where a bot's would
(soundboard.control.streamapi): channel points, cheers, follows, subs and raids to the
alerts, chat lines to the chat commands, whose replies are posted back in chat.

MainWindow makes one ``TwitchLink`` (``MainWindow.twitch``). It lives on the UI thread;
Twitch's HTTP calls (soundboard.online.twitch) run on its own thread and come back here
through ``_answer``. Nothing runs unless the streamer connected, Twitch is offered
(twitch.CLIENT_ID) and its switch in Settings > Privacy & security is on.
"""
from __future__ import annotations

import collections
import json
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from soundboard.control import streamapi
from soundboard.core import usage
from soundboard.core.pollthread import PollThread
from soundboard.i18n import _
from soundboard.online import net, twitch

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

OFF, CONNECTING, ON, PROBLEM = "off", "connecting", "on", "problem"
RETRY_S = (5, 15, 30, 60, 120)   # waits before connecting again after the socket drops
KEEPALIVE_GRACE_S = 10           # on top of Twitch's keepalive before it counts as gone
SEEN_MAX = 500                   # message ids remembered (Twitch may send one twice)


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


class TwitchLink(QObject):
    changed = Signal()                  # state / message / the rewards changed
    code_ready = Signal(str, str)       # signing in: (the code, where to type it)
    login_done = Signal(bool, str)      # signed in (or not, and why)
    _answer = Signal(object, object)    # (then, result) from the worker thread

    def __init__(self, mw: MainWindow):
        super().__init__()
        self.mw = mw
        self.state = OFF
        self.message = ""
        self.rewards: list[str] = []
        self.refused: list[str] = []    # event types Twitch wouldn't send (no channel points…)
        self._worker = PollThread("twitch")
        self._answer.connect(self._on_answer)
        self._sock = None               # the EventSub socket listened to
        self._next = None               # the one Twitch moved us to (session_reconnect)
        self._tries = 0
        self._seen: collections.OrderedDict = collections.OrderedDict()
        self._login = None              # the device code being waited on
        self._login_until = 0.0
        self._gen = 0                   # bumped by stop(): answers for an older run are dropped
        self._retry = self._timer(self.apply)
        self._alive = self._timer(self._went_quiet)
        self._poll = self._timer(self._poll_login)
        self._keepalive_s = 30.0
        net.on_change(self._net_changed)

    # ------------------------------------------------------------------ helpers

    def _timer(self, fn) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(fn)
        return t

    @property
    def connected(self) -> bool:
        """Signed in (whether or not the socket is up right now)."""
        return bool(self.mw.cfg.twitch_token)

    def _run(self, work: Callable[[], object], then: Callable[[object], None]) -> None:
        """work() on the Twitch thread, then(result) back here (an exception is the result)."""
        gen = self._gen

        def job():
            try:
                out = work()
            except Exception as e:  # noqa: BLE001 - handed back and shown, never raised there
                out = e
            self._answer.emit((gen, then), out)
        self._worker.run(job)

    def _on_answer(self, key, out):
        gen, then = key
        if gen != self._gen:   # stopped (disconnected, quit) since it was asked
            return
        then(out)

    def _set(self, state: str, message: str = ""):
        if (state, message) != (self.state, self.message):
            self.state, self.message = state, message
            self.changed.emit()

    def _save(self):
        self.mw._save_now()   # on the saver's thread, never the whole config here

    # ------------------------------------------------------------------ signing in

    def login(self):
        """Ask Twitch for a code; code_ready says what to type where, login_done the end."""
        if not twitch.offered():
            self.login_done.emit(False, _("Twitch sign-in isn't set up in this version."))
            return
        if not net.allowed(twitch.FEATURE):
            self.login_done.emit(False, net.off_message(twitch.FEATURE))
            return
        usage.used("twitch-login")
        self._run(twitch.start_login, self._got_code)

    def cancel_login(self):
        self._login = None
        self._poll.stop()

    def _got_code(self, out):
        if isinstance(out, Exception):
            self.login_done.emit(False, _("Couldn't reach Twitch: {error}", error=str(out)))
            return
        self._login = out
        self._login_until = time.monotonic() + out.expires_in
        self.code_ready.emit(out.user_code, out.url)
        self._poll.start(int(out.interval * 1000))

    def _poll_login(self):
        code = self._login
        if code is None:
            return
        if time.monotonic() > self._login_until:
            self._login = None
            self.login_done.emit(False, _("The code ran out. Try again."))
            return
        self._run(lambda: twitch.finish_login(code.device_code), self._polled)

    def _polled(self, out):
        code = self._login
        if code is None:   # cancelled meanwhile
            return
        if isinstance(out, Exception):
            self._login = None
            usage.used("twitch-login-failed")
            self.login_done.emit(False, _("Twitch said no: {error}", error=str(out)))
            return
        if out is None:   # not yet
            self._poll.start(int(code.interval * 1000))
            return
        self._login = None
        self._run(lambda: (out, twitch.validate(out.access)), self._signed_in)

    def _signed_in(self, out):
        if isinstance(out, Exception):
            usage.used("twitch-login-failed")
            self.login_done.emit(False, _("Couldn't reach Twitch: {error}", error=str(out)))
            return
        tokens, who = out
        cfg = self.mw.cfg
        cfg.twitch_token, cfg.twitch_refresh = tokens.access, tokens.refresh
        cfg.twitch_login = str(who.get("login") or "")
        cfg.twitch_user_id = str(who.get("user_id") or "")
        self._save()
        self.login_done.emit(True, cfg.twitch_login)
        self.apply()

    def disconnect(self):
        """Forget the sign-in (and tell Twitch to forget the token)."""
        cfg = self.mw.cfg
        token = cfg.twitch_token
        self.stop()
        cfg.twitch_token = cfg.twitch_refresh = cfg.twitch_login = cfg.twitch_user_id = ""
        cfg.twitch_share = False
        self.rewards, self.refused = [], []
        self._save()
        if token and net.allowed(twitch.FEATURE):
            self._worker.run(lambda: twitch.revoke(token))
        self._set(OFF)

    # ------------------------------------------------------------------ the socket

    def apply(self):
        """Connect, or stay away, to match the sign-in and the switches."""
        if not self.connected or not twitch.offered():
            self.stop()
            self._set(OFF)
            return
        if not net.allowed(twitch.FEATURE):
            self.stop()
            self._set(PROBLEM, net.off_message(twitch.FEATURE))
            return
        if self._sock is not None:
            return
        self._set(CONNECTING)
        token, refresh = self.mw.cfg.twitch_token, self.mw.cfg.twitch_refresh
        self._run(lambda: self._checked_token(token, refresh), self._token_ok)

    @staticmethod
    def _checked_token(token: str, refresh: str):
        """The token, or new Tokens if Twitch no longer took it (worker thread)."""
        try:
            twitch.validate(token)
            return token
        except twitch.TwitchError as e:
            if e.status != 401 or not refresh:
                raise
        return twitch.refresh(refresh)   # a Tokens: saved back on the UI thread

    def _token_ok(self, out):
        if isinstance(out, twitch.TwitchError) and out.status in (400, 401):
            self.mw.cfg.twitch_token = self.mw.cfg.twitch_refresh = ""
            # as Disconnect: signing in again (maybe as another account) asks again
            self.mw.cfg.twitch_share = False
            self._save()
            self._set(PROBLEM, _("Twitch signed you out. Connect again."))
            return
        if isinstance(out, Exception):
            self._later(_("Couldn't reach Twitch: {error}", error=str(out)))
            return
        if isinstance(out, twitch.Tokens):
            self.mw.cfg.twitch_token, self.mw.cfg.twitch_refresh = out.access, out.refresh
            self._save()
        self._fetch_rewards()
        self._open(twitch.EVENTSUB_WS)

    def _fetch_rewards(self):
        cfg = self.mw.cfg
        token, uid = cfg.twitch_token, cfg.twitch_user_id

        def got(out):
            if isinstance(out, list) and out != self.rewards:
                self.rewards = out
                self.changed.emit()
        self._run(lambda: twitch.rewards(token, uid), got)

    def refresh_rewards(self):
        if self.state == ON:
            self._fetch_rewards()

    def _open(self, url: str, moving: bool = False):
        from PySide6.QtWebSockets import QWebSocket
        sock = QWebSocket()
        sock.setProxy(net.qt_proxy(twitch.FEATURE))   # the relay: the switches, proxy, Tor
        sock.textMessageReceived.connect(lambda text, s=sock: self._message(s, text))
        sock.disconnected.connect(lambda s=sock: self._closed(s))
        if moving:
            self._next = sock
        else:
            self._sock = sock
        sock.open(QUrl(url))

    def _drop(self, sock):
        if sock is None:
            return
        try:
            sock.disconnected.disconnect()
        except (RuntimeError, TypeError):
            pass
        sock.close()
        sock.deleteLater()

    def stop(self):
        self._gen += 1
        self._retry.stop()
        self._alive.stop()
        self.cancel_login()
        for s in (self._sock, self._next):
            self._drop(s)
        self._sock = self._next = None

    def quit(self):
        self.stop()
        self._worker.stop()

    def _later(self, why: str):
        """The socket's gone: try again after a wait that grows."""
        for s in (self._sock, self._next):
            self._drop(s)
        self._sock = self._next = None
        self._alive.stop()
        wait = RETRY_S[min(self._tries, len(RETRY_S) - 1)]
        self._tries += 1
        self._set(PROBLEM, why or _("Lost the connection to Twitch. Trying again…"))
        self._retry.start(wait * 1000)

    def _closed(self, sock):
        if sock is self._sock or sock is self._next:
            self._later(_("Lost the connection to Twitch. Trying again…"))

    def _went_quiet(self):
        self._later(_("Twitch went quiet. Connecting again…"))

    def _net_changed(self):
        # a switch, Offline mode or the proxy changed: start again the new way
        if self.connected:
            self.stop()
            self.apply()

    # ------------------------------------------------------------------ Twitch's messages

    def _message(self, sock, text: str):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        meta = _d(msg.get("metadata"))
        payload = _d(msg.get("payload"))
        kind = meta.get("message_type")
        session = _d(payload.get("session"))
        if kind == "session_welcome":
            self._keepalive(session.get("keepalive_timeout_seconds"))
            if sock is self._next:   # moved by Twitch: the subscriptions come along
                self._drop(self._sock)
                self._sock, self._next = sock, None
                return
            self._subscribe(str(session.get("id") or ""))
        elif kind == "session_keepalive":
            self._keepalive()
        elif kind == "session_reconnect":
            url = str(session.get("reconnect_url") or "")
            if url.startswith("wss://"):
                self._open(url, moving=True)
        elif kind == "notification":
            self._keepalive()
            mid = str(meta.get("message_id") or "")
            if mid:
                if mid in self._seen:
                    return
                self._seen[mid] = True
                while len(self._seen) > SEEN_MAX:
                    self._seen.popitem(last=False)
            self.handle(payload, meta)
        elif kind == "revocation":
            sub = _d(payload.get("subscription"))
            log.info("Twitch stopped sending %s (%s)", sub.get("type"), sub.get("status"))

    def _keepalive(self, seconds=None):
        if seconds:
            self._keepalive_s = float(seconds)
        self._alive.start(int((self._keepalive_s + KEEPALIVE_GRACE_S) * 1000))

    def _subscribe(self, session_id: str):
        cfg = self.mw.cfg
        token, uid = cfg.twitch_token, cfg.twitch_user_id

        def done(out):
            if isinstance(out, twitch.TwitchError) and out.status == 401:
                self.stop()
                self.apply()   # refreshes the token first
                return
            if isinstance(out, Exception):
                self._later(_("Couldn't reach Twitch: {error}", error=str(out)))
                return
            self.refused = out
            self._tries = 0
            self._set(ON)
        self._run(lambda: twitch.subscribe(token, uid, session_id), done)

    def handle(self, payload: dict, meta: dict | None = None) -> tuple[int, object]:
        """One event from Twitch: a chat line to the chat commands (the reply posted back),
        anything else to the alerts. What streamapi answered."""
        mw = self.mw
        sub = _d(payload.get("subscription"))
        event = _d(payload.get("event"))
        chat = sub.get("type") == "channel.chat.message"
        usage.used("twitch-chat" if chat else "twitch-event")   # the kind only (usage.py)
        if chat:
            badges = {b.get("set_id") for b in event.get("badges") or [] if isinstance(b, dict)}
            message = _d(event.get("message"))
            params = {"user": str(event.get("chatter_user_name") or ""),
                      "message": str(message.get("text") or ""),
                      "mod": "1" if "moderator" in badges else "0",
                      "sub": "1" if badges & {"subscriber", "founder"} else "0",
                      "vip": "1" if "vip" in badges else "0",
                      "broadcaster": "1" if "broadcaster" in badges else "0"}
            status, body = streamapi.chat(mw, params)
            reply = body.get("reply") if isinstance(body, dict) else ""
            if reply:
                cfg = mw.cfg
                token, uid = cfg.twitch_token, cfg.twitch_user_id
                self._run(lambda: twitch.send_chat(token, uid, reply), self._sent)
            return status, body
        return streamapi.event(mw, {"_body": {"subscription": sub, "event": event,
                                               "metadata": meta or {}}})

    def _sent(self, out):
        if isinstance(out, Exception):
            log.info("couldn't post the reply in chat: %s", out)
