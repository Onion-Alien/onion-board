"""Local control API: lets a Stream Deck (its "API request" / website actions, Bitfocus
Companion, Touch Portal…), AutoHotkey or a script play pads.

Off unless turned on in Settings → Remote. It listens on 127.0.0.1 only, on
Config.api_port, and every request must carry the token shown in Settings, as
`Authorization: Bearer <token>`, an `X-Token: <token>` header, or `?token=<token>`
for tools that can only open a URL. The token is random, stays in config.json (a
Stream Deck button has to keep working after a restart, so it can't change every
launch), is never exported with a backup, and is never logged; Settings can make a
new one. Requests whose Host isn't this PC's loopback are refused (DNS rebinding),
and no CORS headers are sent, so a web page can't read anything back.

Every endpoint takes GET or POST and answers JSON (ENDPOINTS below is the list;
/api/help returns it, so a script or an AI assistant can look it up):

    /api/status                  version, what's playing / queued, category, live /
                                 voice / mic / hear, speed and effects, mode, radio
    /api/sounds[?q=…&category=…] [{id, name, hotkey, categories, color, playing,
                                 volume, loop, press, plays, duration, effects}]
    /api/categories              ["Memes", ...]
    /api/play?id=… or ?name=…    play a pad (name: exact, any case)
    /api/stop?id=… or ?name=…    stop one sound;  /api/stop alone stops everything
    /api/pause[?on=1|0|toggle]   pause everything / resume (no on=: toggle)
    /api/random[?category=…]     a random sound (default: the category showing;
                                 category= with nothing after it: any sound)
    /api/last                    play the last sound again
    /api/queue?name=… / ?category=…[&shuffle=1] / ?clear=1
                                 play a sound after the ones playing now, or a whole
                                 category one after another; alone: what's up next
    /api/category?name=… / ?step=next|prev   show a category (name= blank: All)
    /api/volume?set=0-1000 / ?step=up|down   the sounds' volume (100: normal)
    /api/live, /api/voice, /api/mic [?on=1|0|toggle]
                                 the Live / Muted switch, the voice changer, "others
                                 hear my mic" (no on=: toggle)
    /api/voice?name=Robot / ?random=1   pick a voice (and turn the voice changer on)
    /api/voices                  the voice changer's voices, and which one is on
    /api/say?text=… / ?stop=1    speak a typed line in the computer voice
    /api/hear[?on=1|0|toggle]    "Hear what they hear": your mic as others hear it
    /api/replay                  save the instant replay as a pad
    /api/speed?set=0.25-2 / ?step=up|down [&keep=1|0|toggle]
    /api/pitch?set=-12-12 / ?step=up|down
                                 the live speed / pitch of every sound (keep: speed
                                 changes leave the pitch alone)
    /api/effects?bass=6&echo=0.3… / ?preset=Canyon / ?reset=1
                                 the live effects on every sound
    /api/reset                   back to 1x, no pitch change, no effects
    /api/mode[?simple=game|?set=discord]   who's listening: a sound mode (Game, Voice
                                 chat, Clean, Advanced) or one exact voice chat mode
    /api/stations?list=popular|favorites|recent|search[&q=…]   radio stations
    /api/radio?id=… / ?on=1|0|toggle         play a station / play or stop the radio
    /api/radio_random, /api/radio_star[?id=…], /api/radio_live, /api/radio_hear,
    /api/radio_volume            the Radio tab's other controls
    /api/apps                    the Apps tab's programs; /api/app?name=…&send=1|0|toggle
                                 [&volume=0-1000] sends one to whoever's listening
    /api/setups, /api/setup?name=…[&tab=sounds|radio|apps]
                                 My setups (saved on the Voice tab) on the live controls
    /api/hotkeys[?on=1|0|toggle] every global hotkey off (to type) or on
    /api/mic_gate[?on=…]         mute my mic while a sound plays
    /api/chat, /api/chat_rules, /api/event, /api/alerts, /api/feed
                                 chat commands, alerts and donations from a streaming
                                 bot (soundboard.control.streamapi)
    /api/help                    this list

A POST may carry its values as a JSON object or a form instead of in the URL (a key in
the URL wins); /api/event also reads the JSON Twitch EventSub, StreamElements,
Streamlabs and Ko-fi send.

The same server, given `lan=True`, is what "remote" add-ons such as Onion Pocket
get (soundboard.ui.remotehost): it listens on this PC's address on the home network
instead, with the add-on's own key, a shorter list of actions, and a page served at
/ without a key (the page holds nothing; Onion Pocket hands the phone its key in the
link's #fragment, which browsers never send). It answers only addresses on the local
network, takes the key only in a header (never ?token=, which would end up in a
browser's history), and an address that gets the key wrong FAIL_LIMIT times in a row
is ignored for LOCK_S seconds. It never listens on a network Windows calls Public
(a café's Wi-Fi), whatever Windows Firewall says (soundboard.online.netcategory). Either
server keeps at most MAX_CONNECTIONS open at once (PEER_CONNECTIONS from one address).

On the home network the key needn't travel at all: a request can instead carry
`X-Sig: <unix time>.<nonce>.<HMAC-SHA256(key, "<time>.<nonce>.<METHOD> <path>")>`
(base64url, no padding), where <path> is the request target as sent ("/api/play?id=…").
Someone reading the Wi-Fi's traffic sees only signatures: each is good for one request,
within SIG_WINDOW_S of this PC's clock and not from before the server (re)started, and a
nonce isn't taken twice while it runs. The nonces are kept in memory only, so after a
restart (of the app, or of the server) a signature from before it is refused by its
time instead: one read off the Wi-Fi can't be sent again then. A wrong key's 401
carries `now`, this PC's clock, so a phone whose clock is off can sign again.
Onion Pocket signs from the version that sees `RemoteHost.signed_requests`; the plain
key header still works for older ones.

The HTTP side runs on its own thread; each request is handed to the UI thread
(`RemoteControl.request`) and answered from there, so it never touches the
window's state from another thread.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import random
import re
import secrets
import selectors
import socket
import threading
import time
import weakref
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QTimer, Signal

from soundboard.core import errors, usage
from soundboard.online import netcategory
from soundboard.control import streamapi
from soundboard.core.pollthread import PollThread
from soundboard.i18n import _

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
DEFAULT_PORT = 7474
ANSWER_S = 3.0          # how long a request waits for the UI thread
IDLE_S = 10.0           # a client that connects and goes quiet is dropped after this
FAIL_LIMIT = 5          # lan: wrong keys in a row from one address before it's locked out
LOCK_S = 60.0           # lan: ...for this long
SIG_WINDOW_S = 300      # lan: a signed request's time may be this far from this PC's
NONCES_MAX = 20000      # lan: nonces remembered (a phone sends one every 2 s or so)
MAX_CONNECTIONS = 32    # connections open at once; more are closed straight away
PEER_CONNECTIONS = 8    # ...and from any one address (a phone uses one or two)
NETWORK_CHECK_S = 30.0  # lan: how often it checks the network is still not Public
WAKE_S = 30.0           # the server thread's longest sleep (halt() wakes it at once)


def public_network() -> str:
    """Why a lan server won't listen, for the app's window (shown as `error`)."""
    return _("Windows calls this network Public (like a café's or a hotel's Wi-Fi), "
             "so phones are turned away. At home, set it to Private in Windows "
             "Settings → Network & internet, then turn this off and on again")


# every endpoint, in the order they're listed (the 404 answer, /api/help, the
# setup prompt and Settings all read this)
ENDPOINTS = {
    "status": "version, what's playing and what's queued, the category showing, live / "
              "voice (and which voice) / mic / hear / volume, the live speed and effects, "
              "the sound mode, the radio",
    "sounds": "every sound: [{id, name, hotkey, categories, color, playing, volume (%), "
              "loop, press (what pressing does), plays, duration (s), effects}]; "
              "?q=horn keeps the names holding that, ?category=Chill one category's",
    "categories": "the category names",
    "play": "play one sound: ?name=Airhorn (exact name, any case) or ?id=…",
    "stop": "stop one sound (?name= or ?id=); with neither, stop everything",
    "pause": "pause everything (?on=1), resume it (?on=0), or flip (?on=toggle or nothing)",
    "random": "a random sound from ?category=… (default: the one showing; "
              "category= blank: any sound)",
    "last": "play the last sound again",
    "queue": "?name= / ?id= plays that sound once the ones playing now finish (answers "
             "\"playing\" when nothing was, so it played at once, else \"queued\"); "
             "?category=Chill plays every sound in it one after another (&shuffle=1: "
             "in a random order); ?clear=1 empties the queue; alone: what's up next",
    "category": "show a category: ?name=Memes (name= blank: All) or ?step=next / prev",
    "volume": "the sounds' volume in %: ?set=0-1000 (100: normal) or ?step=up / down "
          "(10 % a step)",
    "live": "the Live / Muted switch (Muted: others hear none of your sounds; your plain "
            "mic still goes out unless a voice changer is on or Send my mic is off): "
            "?on=1 / 0 / toggle",
    "voice": "the voice changer on / off: ?on=1 / 0 / toggle, or ?name=Robot picks that "
             "voice and turns the changer on (/api/voices lists them); ?random=1 a random "
             "one (never the one on); &seconds=30 with name= or random=: only for that "
             "long, then back to what was on",
    "voices": "the voice changer's voices (the built-in ones and your saved ones), and "
              "which one is on",
    "say": "speak a typed line for others to hear, in the Voice tab's computer voice "
           "(through the voice changer if that's on): ?text=hello there; ?stop=1 stops it",
    "mic": "whether others hear your mic: ?on=1 / 0 / toggle",
    "hear": "Hear what they hear: you hear your mic (and voice changer) the way others "
            "do, to check it: ?on=1 / 0 / toggle",
    "replay": "save the instant replay (the last seconds you heard) as a new sound",
    "speed": "the live speed of every sound: ?set=0.25-2 or ?step=up / down (the quick "
             "speeds); &keep=1 / 0 / toggle: speed changes leave the pitch alone",
    "pitch": "the live pitch of every sound: ?set=-12 to 12 (semitones) or ?step=up / down",
    "effects": "the live effects on every sound: any of ?bass= (-12 to 18 dB) &treble= "
               "(-12 to 12 dB) &muffle= &reverb= &echo= &crunch= (0-1), or ?preset=Canyon, "
               "or ?reset=1; alone: the knobs and presets there are",
    "reset": "live speed, pitch and effects back to normal",
    "mode": "who's listening (the voice chat your sounds are shaped for): "
            "?simple=game / voice / clean / advanced, or one exact mode with "
            "?set=discord; alone: the modes there are",
    "stations": "radio stations: ?list=popular / favorites / recent, or ?list=search&q=jazz "
                "(ask again for the stations found online)",
    "radio": "the radio: ?id=… plays that station; ?on=1 / 0 / toggle plays the last one or "
             "stops it",
    "radio_random": "play a random station: ?list=popular / favorites / recent (default: "
                    "the list showing on the Radio tab)",
    "radio_star": "star / unstar a station in Favorites: ?id=… (default: the one playing), "
                  "&on=1 / 0 / toggle",
    "radio_live": "whether others hear the radio: ?on=1 / 0 / toggle",
    "radio_hear": "whether you hear the radio yourself: ?on=1 / 0 / toggle",
    "radio_volume": "the radio's volume in %: ?set=0-1000 (100: normal) or ?step=up / down "
                "(10 % a step)",
    "apps": "the Apps tab's programs: [{name, exe, running, sending, volume}]",
    "app": "send one program's sound to whoever's listening: ?name=Spotify (its name or "
           "its .exe) &send=1 / 0 / toggle, &volume=0-1000 (%)",
    "setups": "My setups (voice setups saved on the Voice tab) and the one on each live "
              "control (sounds, radio, apps)",
    "setup": "put one of My setups on everything playing: ?name=… (name= blank: none) "
             "&tab=sounds (default) / radio / apps",
    "hotkeys": "every global hotkey off (so the keys type normally) or back on: "
               "?on=1 / 0 / toggle",
    "mic_gate": "mute my mic while a sound plays (others hear only the sound): "
                "?on=1 / 0 / toggle",
    "chat": "one chat line from a bot: ?user=…&message=… (&mod=1 / &sub=1 / &vip=1 / "
            "&broadcaster=1, or &badges= as Twitch sends them). Lines starting with ! are "
            "commands: !sound <name>, !sounds, !random [category], !say <text>, "
            "!voice <name>, !stop; anything else is read out when tts is on. Answers "
            "handled, why not (reason, wait) and reply: a line to post back in chat",
    "chat_rules": "the chat commands' rules: who may use each (?sound= / sounds= / random= "
                  "/ say= / voice= / stop= / tts= everyone, subs, vips, mods, broadcaster "
                  "or off), ?user_cooldown= / cooldown= (s), ?category= (chat plays only "
                  "these), ?blocked=word,word, ?links=0 / 1, ?max_length=, ?prefix=!, "
                  "?voice_seconds=, ?tts_format=, ?reply_list= / reply_missing=, ?on=0 / 1, "
                  "?reset=1; alone: the rules now",
    "event": "an alert or donation: ?type=follow / sub / resub / gift_sub / cheer / raid / "
             "donation / redeem / gift / like / share / hype_train (or a name of your own) "
             "&user= &amount= &message= &reward= &currency= &id= (one id plays once). Does "
             "what /api/alerts set for the type, or &sound= / &category= / &say= / &voice= "
             "(&voice_seconds=) given here; &test=1 fills in a test viewer (a follow "
             "without type=). A POST may send Twitch EventSub, StreamElements, Streamlabs or "
             "Ko-fi JSON as it is",
    "alerts": "what each alert does: ?type=donation&sound=Airhorn (or &category=Chill, "
              "&say=Thanks {user} for {amount}: {message}, &voice=Robot&voice_seconds=30), "
              "&min=10: only from that amount up (the highest one reached plays); "
              "&clear=1 removes it; ?on=0 / 1 all alerts off / on; alone: what's set "
              "(?type=raid alone: that type's rules)",
    "feed": "what chat commands and alerts did, oldest first: ?since=<the last id you "
            "got> (&limit=); answers events and last",
    "help": "this list",
}
ACTIONS = tuple(ENDPOINTS)
BODY_MAX = 64 * 1024    # bytes in a POST's body
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,64}")


def new_token() -> str:
    return secrets.token_urlsafe(24)


@dataclass
class Job:
    action: str
    params: dict
    done: threading.Event = field(default_factory=threading.Event)
    status: int = 500
    body: object = None
    # a request answered "busy" must not still run later (a retrying Stream Deck
    # would play the sound twice); the lock settles which of the two happens
    lock: threading.Lock = field(default_factory=threading.Lock)
    started: bool = False
    cancelled: bool = False


class _Server(ThreadingHTTPServer):
    """One thread per connection, but only so many: past MAX_CONNECTIONS open at once,
    or PEER_CONNECTIONS from one address, a new one is closed straight away. Without
    that, a device on the Wi-Fi with no key could open thousands of connections (each
    a thread fighting the audio thread for Python) and stall the app's sound."""
    daemon_threads = True
    allow_reuse_address = False   # Windows: reuse would let two apps share the port

    def __init__(self, *args, **kwargs):
        self._open: dict[str, int] = {}   # peer -> connections open now
        self._open_lock = threading.Lock()
        self._halting = False
        self._halted = threading.Event()
        self._halted.set()
        try:   # halt()'s wake-up call: a byte on a socket pair the thread also waits on
            self._wake_r, self._wake_w = socket.socketpair()
        except OSError:
            self._wake_r = self._wake_w = None
        try:
            super().__init__(*args, **kwargs)
        except BaseException:
            self._close_wake()
            raise

    def start_thread(self, name: str):
        """serve() on a thread of its own."""
        self._halted.clear()
        threading.Thread(target=self.serve, daemon=True, name=name).start()

    def serve(self):
        """socketserver's serve_forever, but asleep until a connection comes or halt()
        wakes it: serve_forever(poll_interval=0.25) woke 4 times a second all day just
        to see whether it should stop. Without the socket pair it looks every second."""
        try:
            with selectors.DefaultSelector() as sel:
                sel.register(self, selectors.EVENT_READ)
                if self._wake_r is not None:
                    sel.register(self._wake_r, selectors.EVENT_READ)
                timeout = WAKE_S if self._wake_r is not None else 1.0
                while not self._halting:
                    ready = sel.select(timeout)
                    if self._halting:
                        break
                    if any(key.fileobj is self for key, _ in ready):
                        self._handle_request_noblock()   # pyright: ignore[reportAttributeAccessIssue]  # socketserver's
                    self.service_actions()
        finally:
            self._halted.set()

    def halt(self):
        """Stop serve() and wait for it to end (instead of shutdown())."""
        self._halting = True
        if self._wake_w is not None:
            try:
                self._wake_w.send(b"x")
            except OSError:
                pass
        self._halted.wait(5.0)

    def server_close(self):
        super().server_close()
        self._close_wake()

    def _close_wake(self):
        for s in (self._wake_r, self._wake_w):
            if s is not None:
                s.close()

    def process_request(self, request, client_address):
        peer = client_address[0]
        with self._open_lock:
            full = (sum(self._open.values()) >= MAX_CONNECTIONS
                    or self._open.get(peer, 0) >= PEER_CONNECTIONS)
            if not full:
                self._open[peer] = self._open.get(peer, 0) + 1
        if full:
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:   # no thread started: give the slot back
            self._release(peer)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release(client_address[0])

    def _release(self, peer: str):
        with self._open_lock:
            n = self._open.get(peer, 0) - 1
            if n > 0:
                self._open[peer] = n
            else:
                self._open.pop(peer, None)


_running: weakref.WeakSet = weakref.WeakSet()   # the servers listening now
_watchers: list = []   # weak callbacks, called whenever one starts or stops


def on_change(fn) -> None:
    """Call `fn` whenever a server starts or stops (held weakly, like net.on_change).
    It may be called from the thread that stopped one: hand over to the UI thread."""
    ref = weakref.WeakMethod(fn) if hasattr(fn, "__self__") else (lambda f=fn: f)
    _watchers.append(ref)


def listening() -> list[RemoteControl]:
    """The servers listening now (the control API, a remote add-on's)."""
    return [s for s in list(_running) if s.running]


def answer_waiting() -> None:
    """The requests waiting on the UI thread, answered now: only they (no timers, no
    other events). For start-up's long steps before the event loop runs (the update
    check behind the loading screen, building Settings and Edit sound): a Stream Deck
    press then waits one step for its answer, not all of them and then "busy". UI
    thread only, once the window is built."""
    for ctl in listening():
        QCoreApplication.sendPostedEvents(ctl, QEvent.Type.MetaCall.value)


def _changed() -> None:
    for ref in list(_watchers):
        fn = ref()
        if fn is None:
            if ref in _watchers:
                _watchers.remove(ref)
            continue
        try:
            fn()
        except RuntimeError:   # its window is gone
            if ref in _watchers:
                _watchers.remove(ref)


class RemoteControl(QObject):
    """Starts / stops the server. `dispatch(action, params) -> (status, body)` runs on
    the UI thread for every authorised request whose action is in `actions`. `page`,
    (body, headers), is answered at / with no key. `lan` makes it the phone remote's
    server: local-network peers only, wrong keys lock an address out, and never on a
    network Windows calls Public (checked when it starts and every NETWORK_CHECK_S
    after: `closed` says why when that stops it)."""
    request = Signal(object)
    closed = Signal(str)   # lan: stopped by itself, and why
    _net_answer = Signal(object, bool)   # (the server asked about, is the network Public)

    def __init__(self, dispatch, parent=None, *, actions=ACTIONS, page=None,
                 lan: bool = False, name: str = "control API"):
        super().__init__(parent)
        self.dispatch = dispatch
        self.actions = tuple(actions)
        self.page = page
        self.lan = lan
        self.name = name
        self.host = HOST
        self.token = ""
        self.port = 0
        self.error = ""
        self._server: _Server | None = None
        self._fails: dict[str, tuple[int, float]] = {}   # peer -> (wrong keys, locked until)
        self._fails_lock = threading.Lock()
        self._net_poll = PollThread("remote-network-check")
        self._nonces: dict[str, float] = {}   # lan: nonce -> forget it after (monotonic)
        self._started = 0   # lan: the unix second it last started; older signatures refused
        self.request.connect(self._on_request, Qt.ConnectionType.QueuedConnection)
        self._network = QTimer(self)
        self._network.setInterval(int(NETWORK_CHECK_S * 1000))
        self._network.timeout.connect(self._check_network)
        self._net_asking = False
        self._net_answer.connect(self._network_checked, Qt.ConnectionType.QueuedConnection)

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self, port: int, token: str, host: str = HOST) -> bool:
        """(Re)start on `host`:`port`. False (and `error` says why) if it can't listen."""
        self.stop()
        self.token, self.port, self.error, self.host = token, int(port), "", host
        with self._fails_lock:
            self._fails.clear()
            # nonces stay until they're stale: a quick restart still knows them. What it
            # (or a new launch) doesn't know, a signature made before now, signed() refuses
            self._started = int(time.time())
        if not token:
            self.error = "no token"
            return False
        if self.lan and netcategory.category(host) == netcategory.PUBLIC:
            self.error = public_network()
            log.info("%s not started: the network is Public", self.name)
            return False
        try:
            srv = _Server((self.host, self.port), _handler_for(self))
        except (OverflowError, ValueError) as e:   # a port outside 0-65535
            self.error = f"port {self.port} isn't a valid port — pick one from 1024 to 65535"
            log.warning("%s couldn't listen on %s:%s: %s", self.name, self.host, self.port, e)
            return False
        except OSError as e:
            self.error = (f"port {self.port} is already in use — pick another"
                          if getattr(e, "winerror", None) == 10048 or e.errno in (98, 10048)
                          else errors.plain(e))
            log.warning("%s couldn't listen on %s:%s: %s", self.name, self.host, self.port, e)
            return False
        self._server = srv
        self.port = srv.server_address[1]   # (port 0 = any free one, for the tests)
        srv.start_thread(self.name.replace(" ", "-"))
        log.info("%s listening on %s:%s", self.name, self.host, self.port)
        if self.lan:
            self._network.start()
        _running.add(self)
        _changed()
        return True

    def _check_network(self):
        """lan, every NETWORK_CHECK_S: is the network still not Public? Asked on a
        thread (Windows takes ~10 ms to say, which was a stall on the UI thread), the
        answer handled back on the UI thread (_network_checked)."""
        if not self.running or self._net_asking:
            return
        self._net_asking = True
        server, host = self._server, self.host

        def ask():
            try:
                public = netcategory.category(host) == netcategory.PUBLIC
            finally:
                self._net_asking = False
            try:
                self._net_answer.emit(server, public)
            except RuntimeError:   # the window (and this) went away meanwhile
                pass
        self._net_poll.run(ask)

    def _network_checked(self, server, public: bool):
        """lan: the network turned Public (or the PC moved to a Public one keeping its
        address) while it listens: stop. (An answer about a server since replaced by a
        restart is dropped: the restart asked again.)"""
        if public and self.running and server is self._server:
            self.stop()
            self.error = public_network()
            log.info("%s stopped: the network is Public now", self.name)
            self.closed.emit(self.error)

    def stop(self):
        self._network.stop()
        srv, self._server = self._server, None
        if srv is not None:
            srv.halt()
            srv.server_close()
            log.info("%s stopped", self.name)
            _running.discard(self)
            _changed()

    def _on_request(self, job: Job):
        with job.lock:
            if job.cancelled:
                return
            job.started = True
        try:
            job.status, job.body = self.dispatch(job.action, job.params)
            if job.status == 200:   # the name only (usage.py)
                usage.used("remote-used-phone" if self.lan else "remote-used-api")
        except Exception:  # noqa: BLE001 - a bad request must never take the app down
            log.exception("%s request %s failed", self.name, job.action)
            job.status, job.body = 500, {"error": "internal error (see the log)"}
        job.done.set()

    # ------------------------------------------------------------------ requests
    def authorised(self, headers, query: dict, request: str = "") -> bool:
        """`request`: "<METHOD> <target>", what a signature covers."""
        if self.lan and headers.get("X-Sig"):
            return self.signed(headers["X-Sig"], request)
        given = ""
        auth = headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            given = auth[7:].strip()
        given = given or headers.get("X-Token", "")
        if not self.lan:   # the phone page sends a header: on the Wi-Fi a key in the
            given = given or (query.get("token") or [""])[0]   # URL is never taken
        return bool(self.token) and secrets.compare_digest(given.encode(), self.token.encode())

    def signed(self, sig: str, request: str) -> bool:
        """lan: X-Sig is this key's signature of `request`, fresh, and its nonce new."""
        if not self.token:
            return False
        ts, _, rest = sig.strip().partition(".")
        nonce, _, mac = rest.partition(".")
        # isascii: "²" and other digits pass isdigit() but int() refuses them
        if not (ts.isascii() and ts.isdigit() and len(ts) <= 12 and _NONCE.fullmatch(nonce)):
            return False
        if abs(time.time() - int(ts)) > SIG_WINDOW_S:
            return False
        if int(ts) < self._started:   # made before a restart, whose nonces weren't kept
            return False
        want = base64.urlsafe_b64encode(hmac.new(
            self.token.encode(), f"{ts}.{nonce}.{request}".encode(), hashlib.sha256)
            .digest()).decode().rstrip("=")
        if not secrets.compare_digest(mac.encode(), want.encode()):
            return False
        now = time.monotonic()
        with self._fails_lock:
            if self._nonces.get(nonce, 0.0) > now:
                return False   # a request read off the Wi-Fi and sent again
            if len(self._nonces) >= NONCES_MAX:
                self._nonces = {n: t for n, t in self._nonces.items() if t > now}
                if len(self._nonces) >= NONCES_MAX:   # all still fresh: refuse, don't forget
                    return False
            self._nonces[nonce] = now + 2 * SIG_WINDOW_S
        return True

    def host_ok(self, host: str) -> bool:
        if self.host != HOST:
            return host in (f"{self.host}:{self.port}", self.host)
        return host in (f"{HOST}:{self.port}", f"localhost:{self.port}", HOST, "localhost")

    def peer_ok(self, peer: str) -> bool:
        """On the lan: only addresses on a local network (a port forwarded from the
        internet, or a VPN's range, gets nothing)."""
        if not self.lan:
            return True
        try:
            ip = ipaddress.ip_address(peer)
        except ValueError:
            return False
        return ip.is_private or ip.is_link_local

    def locked(self, peer: str) -> bool:
        if not self.lan:
            return False
        with self._fails_lock:
            return self._fails.get(peer, (0, 0.0))[1] > time.monotonic()

    def failed(self, peer: str):
        """A wrong key from `peer`: FAIL_LIMIT in a row lock it out for LOCK_S."""
        if not self.lan:
            return
        with self._fails_lock:
            if len(self._fails) > 1024:   # a scan of the whole network: start over
                self._fails.clear()
            n = self._fails.get(peer, (0, 0.0))[0] + 1
            self._fails[peer] = ((0, time.monotonic() + LOCK_S) if n >= FAIL_LIMIT
                                 else (n, 0.0))
            if n >= FAIL_LIMIT:
                log.warning("%s: an address got the key wrong %d times, ignored for %ds",
                            self.name, n, LOCK_S)   # (no address: logs go in bug reports)

    def succeeded(self, peer: str):
        if self.lan:
            with self._fails_lock:
                self._fails.pop(peer, None)


def _handler_for(ctl: RemoteControl):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OnionBoardAPI"
        sys_version = ""
        timeout = IDLE_S

        def log_message(self, fmt, *args):   # the query string may hold the token
            pass

        def _answer(self, status: int, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _page(self):
            assert ctl.page is not None   # _go checked
            body, headers = ctl.page
            self.send_response(200)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict | None:
            """A POST's JSON object or form as params (the JSON is also kept whole in
            "_body"); None if it's too big."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0:
                return {}
            if n > BODY_MAX:   # read (up to a point) so the client gets the answer
                left = min(n, 16 * BODY_MAX)
                while left > 0 and self.rfile.read(min(left, BODY_MAX)):
                    left -= BODY_MAX
                self.close_connection = True
                return None
            text = self.rfile.read(n).decode("utf-8", "replace")
            kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if kind == "application/x-www-form-urlencoded":
                return {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items()
                        if k != "token"}
            try:
                data = json.loads(text)
            except ValueError:
                return {}
            if not isinstance(data, dict):
                return {}
            out: dict[str, object] = {"_body": data}
            for k, v in data.items():
                if k == "token" or not isinstance(k, str):
                    continue
                if isinstance(v, bool):
                    out[k] = "1" if v else "0"
                elif isinstance(v, (str, int, float)):
                    out[k] = str(v)
            return out

        def _go(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query, keep_blank_values=True)
            peer = self.client_address[0]
            if not ctl.peer_ok(peer):
                return self._answer(403, {"error": "only this network"})
            if not ctl.host_ok(self.headers.get("Host", "")):
                return self._answer(403, {"error": "wrong host"})
            if ctl.page and url.path in ("/", "/index.html") and self.command == "GET":
                return self._page()
            if ctl.locked(peer):
                return self._answer(429, {"error": "too many wrong keys: wait a minute"})
            if not ctl.authorised(self.headers, query, f"{self.command} {self.path}"):
                ctl.failed(peer)
                body: dict[str, object] = {"error": "missing or wrong token"}
                if ctl.lan:   # so a phone whose clock is off can sign again
                    body["now"] = int(time.time())
                return self._answer(401, body)
            ctl.succeeded(peer)
            action = url.path.strip("/").removeprefix("api/").removeprefix("api")
            if action not in ctl.actions:
                return self._answer(404, {"error": "unknown endpoint",
                                          "endpoints": [f"/api/{a}" for a in ctl.actions]})
            sent = self._body()
            if sent is None:
                return self._answer(413, {"error": f"the body is too big: at most "
                                                   f"{BODY_MAX // 1024} KB"})
            if ctl.lan:   # (read all the same:) X-Sig signs the URL, not the body
                sent = {}
            params = {**sent, **{k: v[0] for k, v in query.items() if k != "token"}}
            job = Job(action, params)
            ctl.request.emit(job)
            if not job.done.wait(ANSWER_S):
                with job.lock:
                    job.cancelled = not job.started
                if job.cancelled:
                    return self._answer(503, {"error": "the app is busy, try again"})
                job.done.wait()   # it got going just now: answer what it did
            self._answer(job.status, job.body)

        do_GET = do_POST = _go

    return Handler


# --------------------------------------------------------------------------- the app side

def on_value(params: dict, now: bool) -> bool | None:
    """?on=1 / 0 / toggle (or nothing: toggle) -> the new state; None if it's neither."""
    v = (params.get("on") or "toggle").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return not now if v == "toggle" else None


BAD_ON = {"error": "on= takes 1, 0 or toggle"}


# An Onion Watch alarm rings its pad as the voice "<sound id>:ring:<trigger>"
# (soundboard.ui.triggershost.RING): a phone or Stream Deck sees it as the pad playing.
RING = ":ring:"


def pad_of(voice: str) -> str:
    """The sound a playing voice is: an alarm's ring is its pad's."""
    return voice.split(RING, 1)[0]


def dispatch(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    """Carry out one request on the window (UI thread)."""
    cfg = mw.cfg
    playing = mw.engine.playing()
    sounding = list(dict.fromkeys(pad_of(v) for v in playing))
    if action == "help":
        return 200, {"endpoints": {f"/api/{a}": d for a, d in ENDPOINTS.items()},
                     "key": "send it as ?token=…, an X-Token header or Authorization: "
                            "Bearer …"}
    if action == "status":
        from soundboard import __version__
        return 200, {"version": __version__, "category": cfg.category,
                     "playing": [s for s in sounding if s in mw.pads],
                     "paused": bool(playing) and all(p for _, p in playing.values()),
                     "live": bool(mw.engine.sending),
                     "voice": mw.voice.fx.btn_power.isChecked(),
                     "voice_name": getattr(mw.voice.fx, "preset", ""),
                     "mic": bool(cfg.mic_enabled),
                     "hear": bool(mw.engine.mic_check),
                     **queue_state(mw),
                     "volume": mw.vol_sound.spin.value(),
                     **live_state(mw), **mode_state(mw, full=False),
                     "radio": radio_state(mw)}
    if action == "sounds":
        q = (params.get("q") or "").strip().casefold()
        cat = None
        if params.get("category"):
            cat = find_category(cfg, params["category"])
            if cat is None:
                return 404, {"error": f"no category called {params['category']!r}",
                             "categories": list(cfg.categories)}
        return 200, [{"id": m.id, "name": m.name, "hotkey": m.hotkey,
                      "categories": list(m.tags), "color": m.color,
                      "playing": m.id in sounding, "volume": round(m.volume * 100),
                      "loop": m.loop, "press": m.mode, "plays": m.plays,
                      "duration": round(m.duration, 2), "effects": bool(m.fx)}
                     for m in cfg.sounds
                     if (not q or q in m.name.casefold()) and (cat is None or cat in m.tags)]
    if action == "categories":
        return 200, list(cfg.categories)
    if action == "pause":
        paused = bool(playing) and all(p for _, p in playing.values())
        on = on_value(params, paused)
        if on is None:
            return 400, BAD_ON
        return 200, {"paused": mw.engine.pause_all(on)}
    if action == "random":
        cat = params.get("category")
        if cat:
            cat = find_category(cfg, cat)
            if cat is None:
                return 404, {"error": f"no category called {params['category']!r}",
                             "categories": list(cfg.categories)}
        sid = mw.playctl.play_random(cat)
        if sid is None:
            return 404, {"error": "no sound to play there"}
        m = mw.meta(sid)
        return 200, {"playing": sid, "name": m.name if m is not None else ""}
    if action == "last":
        sid = getattr(mw.playctl, "_last_sid", None)
        m = mw.meta(sid) if sid is not None else None
        if sid is None or m is None:
            return 404, {"error": "nothing has played yet"}
        if sid not in mw.audio:
            return 409, {"error": "that sound hasn't loaded (yet)"}
        mw.playctl.play(sid)
        return 200, {"playing": sid, "name": m.name}
    if action == "category":
        step = (params.get("step") or "").strip().lower()
        if step:
            if step not in ("next", "prev", "previous"):
                return 400, {"error": "step= takes next or prev"}
            mw.hkctl.step_category(1 if step == "next" else -1)
        elif "name" in params:
            name = params["name"].strip()
            match = find_category(cfg, name)
            if name and name.lower() != "all" and match is None:
                return 404, {"error": f"no category called {name!r}",
                             "categories": list(cfg.categories)}
            mw.catctl.set_category(match or "")
        else:
            return 400, {"error": "say which: ?name=… or ?step=next / prev"}
        return 200, {"category": cfg.category}
    if action == "volume":
        err = set_volume(mw.vol_sound.spin, params)   # -> set_option("sound_vol")
        return err or (200, {"volume": mw.vol_sound.spin.value()})
    if action == "queue":
        return dispatch_queue(mw, params)
    if action in VOICE_ACTIONS:
        return dispatch_voice(mw, action, params)
    if action in LIVE_ACTIONS:
        return dispatch_live(mw, action, params)
    if action == "mode":
        return dispatch_mode(mw, params)
    if action in APP_ACTIONS:
        return dispatch_apps(mw, action, params)
    if action in ("setups", "setup"):
        return dispatch_setups(mw, action, params)
    if action in streamapi.STREAM_ACTIONS:
        return streamapi.dispatch(mw, action, params)
    if action == "hotkeys":
        on = on_value(params, mw.hkctl.hotkeys_on)
        if on is None:
            return 400, BAD_ON
        mw.hkctl.set_hotkeys_on(on, remote=True)
        return 200, {"hotkeys": mw.hkctl.hotkeys_on}
    if action == "mic_gate":
        on = on_value(params, bool(cfg.mic_gate))
        if on is None:
            return 400, BAD_ON
        set_mic_gate(mw, on)
        return 200, {"mic_gate": bool(cfg.mic_gate)}
    if action in RADIO_ACTIONS:
        return dispatch_radio(mw, action, params)
    if action == "live":
        on = on_value(params, bool(mw.engine.sending))
        if on is None:
            return 400, BAD_ON
        mw.set_sending(on)
        return 200, {"live": bool(mw.engine.sending)}
    if action == "mic":
        on = on_value(params, bool(cfg.mic_enabled))
        if on is None:
            return 400, BAD_ON
        mw.chk_mic.setChecked(on)   # -> on_mic_toggle
        return 200, {"mic": bool(cfg.mic_enabled)}
    if action == "hear":
        on = on_value(params, bool(mw.engine.mic_check))
        if on is None:
            return 400, BAD_ON
        mw.btn_check.setChecked(on)   # -> on_mic_check
        return 200, {"hear": bool(mw.engine.mic_check)}
    if action == "replay":
        from soundboard.audio.engine import SR
        if len(mw.replay.clip()) < int(0.2 * SR):
            return 409, {"error": mw.replay.error or "nothing has played on this PC lately"}
        mw.hkctl.save_replay()
        return 200, {"saved": True}
    # play / stop: one sound, by id or name
    if action == "stop" and not ("id" in params or "name" in params):
        mw.playctl.stop_all()
        return 200, {"stopped": "all"}
    m = find_sound(mw, params)
    if m is None:
        return no_sound(cfg, params)
    if action == "stop":
        mw.engine.stop(m.id)
        for v in playing:   # and a Watch alarm ringing it (its bar clears by itself)
            if v.startswith(m.id + RING):
                mw.engine.stop(v)
        return 200, {"stopped": m.id}
    if m.id not in mw.audio:
        return 409, {"error": "that sound hasn't loaded (yet)"}
    mw.playctl.play(m.id)
    return 200, {"playing": m.id, "name": m.name}


def no_sound(cfg, params: dict) -> tuple[int, dict]:
    """The answer when ?id= / ?name= names no sound."""
    if not params:
        return 400, {"error": "say which: ?id=… or ?name=…"}
    body = {"error": "no such sound"}
    if params.get("name"):   # a typo'd button: say what it probably meant
        close = difflib.get_close_matches(params["name"].strip(),
                                          [s.name for s in cfg.sounds], 3, 0.5)
        if close:
            body["did_you_mean"] = close
    return 404, body


# --------------------------------------------------------------------------- the queue

def queue_state(mw: MainWindow) -> dict:
    return {"queue": [{"id": s, "name": m.name} for s in mw.playctl._queue
                      if (m := mw.meta(s)) is not None]}


def dispatch_queue(mw: MainWindow, params: dict) -> tuple[int, object]:
    """The play queue (the pad menu's Play next, a category's Play all)."""
    if (params.get("clear") or "").strip() not in ("", "0"):
        mw.playctl._queue.clear()
        mw.playctl._say_queue()
        return 200, queue_state(mw)
    if "category" in params:
        cat = find_category(mw.cfg, params["category"])
        if cat is None:
            return 404, {"error": f"no category called {params['category']!r}",
                         "categories": list(mw.cfg.categories)}
        if not any(m.id in mw.audio for m in mw.cfg.sounds if cat in m.tags):
            return 404, {"error": "no sound to play there"}
        shuffled = (params.get("shuffle") or "").strip().lower() in ("1", "true", "on", "yes")
        mw.playctl.queue_category(cat, shuffled)
        return 200, {"category": cat, **queue_state(mw)}
    if not ("id" in params or "name" in params):
        return 200, queue_state(mw)
    m = find_sound(mw, params)
    if m is None:
        return no_sound(mw.cfg, params)
    if m.id not in mw.audio:
        return 409, {"error": "that sound hasn't loaded (yet)"}
    now = mw.playctl.queue_sound(m.id)   # nothing playing: it plays at once, not after anything
    return 200, {"playing" if now else "queued": m.id, "name": m.name, **queue_state(mw)}


# --------------------------------------------------------------------------- the Voice tab

VOICE_ACTIONS = ("voice", "voices", "say")
SAY_MAX = 500           # characters in one ?text=


def voice_names(mw: MainWindow) -> list[str]:
    """The voices a request can pick: the built-in ones, then the saved ones ("My own
    mix" isn't one: picking it opens a window to make it)."""
    from soundboard import voicefx
    return list(voicefx.PRESETS) + [n for n in _voice_tab(mw).fx.store.voices
                                    if n not in voicefx.PRESETS]


def _voice_tab(mw: MainWindow):
    """The Voice tab, for a caller that checked mw.tabctl.tab_on("voice")."""
    from soundboard.ui.taboff import VoiceOff
    voice = mw.voice
    assert not isinstance(voice, VoiceOff)   # switched on: the real tab
    return voice


def voice_state(mw: MainWindow) -> dict:
    fx = _voice_tab(mw).fx
    return {"voice": fx.btn_power.isChecked(), "voice_name": fx.preset}


def dispatch_voice(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    from soundboard import voicefx
    if not mw.tabctl.tab_on("voice"):
        return 409, VOICE_OFF
    fx = _voice_tab(mw).fx
    if action == "voices":
        saved = fx.store.voices
        return 200, {**voice_state(mw),
                     "voices": [{"name": n, "shown": voicefx.shown(n), "saved": n in saved}
                                for n in voice_names(mw)]}
    if action == "say":
        sp = _voice_tab(mw).speech
        if (params.get("stop") or "").strip() not in ("", "0"):
            sp.ctl.stop_speaking()
            return 200, {"stopped": True}
        text = " ".join((params.get("text") or "").split())
        if not text:
            return 400, {"error": "say what: ?text=…"}
        if len(text) > SAY_MAX:
            return 400, {"error": f"text= is too long: at most {SAY_MAX} characters"}
        sp.say_line(text)
        return 200, {"saying": text}
    seconds = None
    if "seconds" in params:
        seconds = number(params, "seconds", 0, streamapi.VOICE_S_MAX)
        if seconds is None:
            return 400, {"error": f"seconds= takes a number, 0 to {streamapi.VOICE_S_MAX}"}
    if (params.get("random") or "").strip() not in ("", "0"):
        pool = fx._roll_pool()
        if not pool:
            return 404, {"error": "no other voice to pick"}
        name = random.choice(pool)
        if seconds:
            return 200, streamapi.voice_for(mw, name, seconds)
        fx.pick(name)
        return 200, voice_state(mw)
    if "name" in params:   # voice?name=Robot
        want = params["name"].strip().casefold()
        names = voice_names(mw)
        match = next((n for n in names
                      if want in (n.casefold(), voicefx.shown(n).casefold())), None)
        if match is None:
            body = {"error": f"no voice called {params['name']!r}", "voices": names}
            close = difflib.get_close_matches(params["name"].strip(), names, 3, 0.5)
            if close:
                body["did_you_mean"] = close
            return 404, body
        if seconds:
            return 200, streamapi.voice_for(mw, match, seconds)
        fx.pick(match)
        return 200, voice_state(mw)
    on = on_value(params, fx.btn_power.isChecked())
    if on is None:
        return 400, BAD_ON
    mw.hkctl._set_voice(on)
    return 200, voice_state(mw)


def set_volume(spin, params: dict) -> tuple[int, dict] | None:
    """?set=0-<the box's maximum> / ?step=up|down (10 % a step) on a volume box: an error answer, or
    None once it's set."""
    step = (params.get("step") or "").strip().lower()
    if "set" in params:
        try:
            new = round(float(params["set"]))
        except (ValueError, OverflowError):   # "loud", nan / inf, 1e999
            return 400, {"error": f"set= takes a number, 0-{spin.maximum()}"}
    elif step in ("up", "down", "+", "-"):
        new = (round(spin.value() / 10) + (1 if step in ("up", "+") else -1)) * 10
    else:
        return 400, {"error": f"say how: ?set=0-{spin.maximum()} or ?step=up / down"}
    spin.setValue(min(max(new, 0), spin.maximum()))
    return None


def number(params: dict, key: str, lo: float, hi: float) -> float | None:
    """params[key] as a number kept within lo..hi; None if it isn't one."""
    try:
        v = float(params[key])
    except (KeyError, TypeError, ValueError):
        return None
    return None if math.isnan(v) else min(max(v, lo), hi)


# --------------------------------------------------------------------------- live controls
# The speed / pitch / effects popup on the Sounds tab's transport bar
# (ui/speedpitch.SpeedPitchButton). Requests go through the popup itself, so the PC's
# sliders always show what's playing.

LIVE_ACTIONS = ("speed", "pitch", "effects", "reset")


def live_state(mw: MainWindow) -> dict:
    from soundboard.audio import livefx
    b = mw.speed_btn
    speed, pitch, keep = b.values()
    fx = b.fx_values()
    preset = next((n for n, a in livefx.PRESETS.items() if livefx.clean(a) == fx), "")
    return {"speed": round(speed, 3), "pitch": round(pitch, 2), "keep_pitch": keep,
            "effects": {k: round(v, 3) for k, v in fx.items()}, "preset": preset}


def dispatch_live(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    from soundboard.audio import livefx
    from soundboard.ui import speedpitch as sp
    b = mw.speed_btn
    speed, pitch, keep = b.values()
    if action == "reset":
        b.reset()
        return 200, live_state(mw)
    if action == "effects":
        if (params.get("reset") or "").strip() not in ("", "0"):
            b.set_fx({})
            return 200, live_state(mw)
        if "preset" in params:
            name = params["preset"].strip().lower()
            match = next((n for n in livefx.PRESETS if n.lower() == name), None)
            if match is None and name not in ("", "none", "off"):
                return 404, {"error": f"no preset called {params['preset']!r}",
                             "presets": list(livefx.PRESETS)}
            b.set_fx(livefx.PRESETS[match] if match else {})
            return 200, live_state(mw)
        knobs = {q.key: q for q in livefx.PARAMS}
        given = [k for k in params if k in knobs]
        if not given:   # what there is to set
            return 200, {**live_state(mw), "presets": list(livefx.PRESETS),
                         "knobs": [{"key": q.key, "label": q.label, "lo": q.lo, "hi": q.hi,
                                    "unit": q.unit.strip()} for q in livefx.PARAMS]}
        amounts = b.fx_values()
        for k in given:
            v = number(params, k, knobs[k].lo, knobs[k].hi)
            if v is None:
                return 400, {"error": f"{k}= takes a number, {knobs[k].lo:g} to "
                                      f"{knobs[k].hi:g}"}
            amounts[k] = v
        b.set_fx(amounts)
        return 200, live_state(mw)
    # speed / pitch
    if "keep" in params:
        k = on_value({"on": params["keep"]}, keep)
        if k is None:
            return 400, {"error": "keep= takes 1, 0 or toggle"}
        keep = k
    step = (params.get("step") or "").strip().lower()
    q, now = (sp.SPEED, speed) if action == "speed" else (sp.PITCH, pitch)
    if "set" in params:
        v = number(params, "set", q.lo, q.hi)
        if v is None:
            return 400, {"error": f"set= takes a number, {q.lo:g} to {q.hi:g}"}
    elif step in ("up", "down", "+", "-"):
        up = step in ("up", "+")
        if action == "speed":   # the next quick speed (0.5, 0.75, 1, 1.25, 1.5, 2)
            ladder = [s for s in sp.QUICK if (s > now + 1e-6 if up else s < now - 1e-6)]
            v = (min(ladder) if up else max(ladder)) if ladder else now
        else:
            v = round(now) + (1 if up else -1)
        if q.lo <= now <= q.hi:          # a Redline value set on the PC stays as it is
            v = min(max(v, q.lo), q.hi)
    elif "keep" in params:
        v = now
    else:
        return 400, {"error": f"say how: ?set={q.lo:g} to {q.hi:g} or ?step=up / down"}
    if action == "speed":
        speed = v
    else:
        pitch = v
    b.set_values(speed, pitch, keep)
    return 200, live_state(mw)


# --------------------------------------------------------------------------- who's listening

def mode_state(mw: MainWindow, full: bool = True) -> dict:
    from soundboard.mic import destination, profiles
    d = mw.cfg.dest if isinstance(mw.cfg.dest, dict) else {}
    now = destination.resolve(d)
    p = profiles.current(d)
    out: dict[str, object] = {"mode": now.key, "mode_label": now.label, "simple": p.key,
           "simple_label": p.label,
           "explain": profiles.explain(d, getattr(mw, "mode_why", ""), english=True)}
    if full:
        out["modes"] = [{"key": m.key, "label": m.label, "note": m.note}
                        for m in destination.all_modes(d.get("custom"))]
        out["simples"] = [{"key": q.key, "label": q.label, "summary": q.summary,
                           "details": q.details} for q in profiles.PROFILES]
    return out


def dispatch_mode(mw: MainWindow, params: dict) -> tuple[int, object]:
    """?simple= picks a simple mode (Game, Voice chat, Clean, Advanced); ?set= one exact
    destination mode, which is Advanced (or Clean, for Off). Both apply and save, and
    the Sounds tab's dropdown and the Setup tab's picker show it."""
    from soundboard.mic import destination, profiles
    from soundboard.ui import destpanel
    if "simple" in params:
        want = params["simple"].strip().lower()
        p = next((q for q in profiles.PROFILES if want in (q.key, q.label.lower())), None)
        if p is None:
            return 404, {"error": f"no sound mode called {params['simple']!r}",
                         **mode_state(mw)}
        destpanel.set_simple(mw, p.key)
    elif "set" in params:
        d = mw.cfg.dest if isinstance(mw.cfg.dest, dict) else {}
        want = params["set"].strip().lower()
        match = next((m for m in destination.all_modes(d.get("custom"))
                      if want in (m.key.lower(), m.label.lower())), None)
        if match is None:
            return 404, {"error": f"no mode called {params['set']!r}", **mode_state(mw)}
        destpanel.set_exact(mw, match.key)
    return 200, mode_state(mw)


# --------------------------------------------------------------------------- the Apps tab

APP_ACTIONS = ("apps", "app")
APPS_OFF = {"error": "the Apps tab is switched off in Onion Board's Settings > Tabs"}


def _apps_tab(mw: MainWindow):
    from soundboard.ui.appspanel import AppsTab
    a = getattr(mw, "apps", None)
    return a if isinstance(a, AppsTab) else None


def app_dict(row) -> dict:
    return {"name": row.name.text(), "exe": row.exe, "running": row.app is not None,
            "sending": row.sending, "volume": row.vol.spin.value()}


def dispatch_apps(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    """The Apps tab's Send switch and volume, through the cards themselves, so the PC
    shows what a request did."""
    tab = _apps_tab(mw)
    if tab is None:
        return 409, APPS_OFF
    rows = list(tab.rows.values())
    if action == "apps":
        return 200, [app_dict(r) for r in rows]
    asked = (params.get("name") or params.get("exe") or "").strip()
    want = asked.casefold()
    if not want:
        return 400, {"error": "say which: ?name=… (/api/apps lists them)"}
    row = next((r for r in rows
                if want in (r.exe.casefold(), r.exe.casefold().removesuffix(".exe"),
                            r.name.text().strip().casefold())), None)
    if row is None:
        return 404, {"error": f"no program called {asked!r} on the Apps tab",
                     "apps": [r.exe for r in rows]}
    if "volume" in params:
        err = set_volume(row.vol.spin, {"set": params["volume"]})
        if err:
            return err
    if "send" in params:
        on = on_value({"on": params["send"]}, row.sending)
        if on is None:
            return 400, {"error": "send= takes 1, 0 or toggle"}
        if on and row.app is None:
            return 409, {"error": "that program isn't running", **app_dict(row)}
        if on != row.sending:
            row.btn_send.setChecked(on)   # -> AppsTab._on_send
    return 200, app_dict(row)


SETUP_TABS = ("sounds", "radio", "apps")


def setups_state(mw: MainWindow) -> dict:
    ls = mw.livesetups
    return {"setups": list(ls.setups()),
            "on": {t: ls.names.get(t, "") for t in SETUP_TABS if ls.button(t) is not None}}


def dispatch_setups(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    """My setups on a live control, as its chips pick them (without the question an AI
    voice or a language asks first: a button can't answer it)."""
    ls = mw.livesetups
    if action == "setups":
        return 200, setups_state(mw)
    tab = (params.get("tab") or "sounds").strip().lower()
    if tab not in SETUP_TABS:
        return 400, {"error": "tab= takes sounds, radio or apps"}
    if ls.button(tab) is None:
        return 409, RADIO_OFF if tab == "radio" else APPS_OFF
    if "name" not in params:
        return 400, {"error": "say which: ?name=… (/api/setups lists them)"}
    want = params["name"].strip().casefold()
    names = list(ls.setups())
    match = next((n for n in names if n.casefold() == want), None)
    if want and match is None:
        body = {"error": f"no setup called {params['name']!r}", "setups": names}
        close = difflib.get_close_matches(params["name"].strip(), names, 3, 0.5)
        if close:
            body["did_you_mean"] = close
        return 404, body
    ls.pick(tab, match or "", ask=False)
    return 200, setups_state(mw)


def set_mic_gate(mw: MainWindow, on: bool):
    """Mute my mic while a sound plays: saved, on the engine, and the Who's listening
    boxes showing it."""
    from soundboard.ui import destpanel
    mw.cfg.mic_gate = on
    destpanel.apply_send(mw.cfg, mw.engine)
    for panel in mw.findChildren(destpanel.DestPanel):
        panel.chk_gate.blockSignals(True)
        panel.chk_gate.setChecked(on)
        panel.chk_gate.blockSignals(False)
    mw._save_later()


# --------------------------------------------------------------------------- the radio
# The Radio tab (ui/radiopanel.RadioTab) does the work, so the PC shows what was picked.
# With Radio switched off in Settings > Privacy & security there's no radio at all.

RADIO_ACTIONS = ("stations", "radio", "radio_random", "radio_star", "radio_live",
                 "radio_hear", "radio_volume")
STATIONS_MAX = 100      # stations in one answer
RADIO_LISTS = ("popular", "favorites", "favourites", "recent")
RADIO_OFF = {"error": "the radio is switched off in Onion Board's Settings (Privacy & "
                      "security, or Tabs)"}
VOICE_OFF = {"error": "the Voice tab is switched off in Onion Board's Settings > Tabs"}


def _radio_tab(mw: MainWindow):
    from soundboard.ui.radiopanel import RadioTab
    r = getattr(mw, "radio", None)
    return r if isinstance(r, RadioTab) else None


def station_dict(r, s) -> dict:
    now = r.player.station
    return {"id": s.uuid, "name": s.name, "country": s.country, "tags": list(s.tags[:3]),
            "bitrate": s.bitrate, "fav": s.uuid in r._fav_ids,
            "playing": now is not None and now.uuid == s.uuid}


def radio_state(mw: MainWindow) -> dict:
    r = _radio_tab(mw)
    if r is None:
        return {"available": False}
    st = r.player.station
    return {"available": True, "on": st is not None,
            "connecting": st is not None and r.player.status == "connecting",
            "station": station_dict(r, st) if st is not None else None,
            "title": r._title if st is not None else "",
            "live": bool(mw.engine.radio_live), "hear": r.chk_hear.isChecked(),
            "volume": r.vol.spin.value(), "last": bool(r.cfg.radio.get("last"))}


def dispatch_radio(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    r = _radio_tab(mw)
    if r is None:
        return 409, RADIO_OFF
    if action == "stations":
        which = (params.get("list") or "popular").strip().lower()
        if which not in RADIO_LISTS + ("search",):
            return 400, {"error": "list= takes popular, favorites, recent or search"}
        stations, loading, error = r.phone_list(which, params.get("q") or "")
        return 200, {"list": which, "loading": loading, "error": error,
                     "stations": [station_dict(r, s) for s in stations[:STATIONS_MAX]]}
    if action == "radio":
        if params.get("id"):
            s = r._stations.get(params["id"])
            if s is None:
                return 404, {"error": "no such station (list them with /api/stations)"}
            r.play(s)
        elif "on" in params or not params:
            on = on_value(params, r.is_active())
            if on is None:
                return 400, BAD_ON
            if on and not r.is_active():
                from soundboard.online.radio import Station
                s = Station.from_saved(r.cfg.radio.get("last") or {})
                if s is None:
                    return 404, {"error": "no station has played yet: pick one"}
                r.play(r._stations.setdefault(s.uuid, s))
            elif not on:
                r.stop()
        else:
            return 400, {"error": "say which: ?id=… or ?on=1 / 0 / toggle"}
        return 200, radio_state(mw)
    if action == "radio_random":
        which = (params.get("list") or "").strip().lower()
        if not which:
            r.start()
            r.play_random()
            if not r.is_active():
                return 404, {"error": "no station to pick from yet"}
            return 200, radio_state(mw)
        if which not in RADIO_LISTS:
            return 400, {"error": "list= takes popular, favorites or recent"}
        now = r.player.station
        pool = [s for s in r.phone_list(which, "")[0] if now is None or s.uuid != now.uuid]
        if not pool:
            return 404, {"error": "no station to pick from there"}
        r.play(random.choice(pool))
        return 200, radio_state(mw)
    if action == "radio_star":
        s = r._stations.get(params["id"]) if params.get("id") else r.player.station
        if s is None:
            return 404, {"error": "no such station" if params.get("id") else
                         "nothing is playing: say which with ?id=…"}
        on = on_value(params, s.uuid in r._fav_ids)
        if on is None:
            return 400, BAD_ON
        if on != (s.uuid in r._fav_ids):
            r._toggle_fav(s.uuid)
            r._update_buttons()
        return 200, {"id": s.uuid, "fav": s.uuid in r._fav_ids}
    if action == "radio_live":
        on = on_value(params, bool(mw.engine.radio_live))
        if on is None:
            return 400, BAD_ON
        r._on_live(on)
        return 200, radio_state(mw)
    if action == "radio_hear":
        on = on_value(params, r.chk_hear.isChecked())
        if on is None:
            return 400, BAD_ON
        r.chk_hear.setChecked(on)   # -> _on_hear
        return 200, radio_state(mw)
    err = set_volume(r.vol.spin, params)   # radio_volume -> _on_vol
    return err or (200, radio_state(mw))


def find_category(cfg, name: str) -> str | None:
    """A category by name, any case; None if there's no such one."""
    name = name.strip().lower()
    return next((c for c in cfg.categories if c.lower() == name), None)


def find_sound(mw: MainWindow, params: dict):
    if params.get("id"):
        return mw.meta(params["id"])
    name = (params.get("name") or "").strip().lower()
    if name:
        return next((m for m in mw.cfg.sounds if m.name.lower() == name), None)
    return None


def apply(mw: MainWindow, ctl: RemoteControl) -> str:
    """Start or stop the server to match the settings. Returns an error ("" if fine)."""
    cfg = mw.cfg
    if not cfg.api_enabled:
        ctl.stop()
        return ""
    if not cfg.api_token:
        cfg.api_token = new_token()
        mw._save_now()   # on the saver's thread: never the whole config on the UI thread
    if ctl.running and ctl.port == cfg.api_port and ctl.token == cfg.api_token:
        return ""
    ctl.start(cfg.api_port, cfg.api_token)
    return ctl.error


# --------------------------------------------------------------------------- AI setup prompt

KEY_PLACEHOLDER = "YOUR-KEY"
PROMPT_SOUNDS = 120     # a big library: list this many names, the AI can ask for the rest


def setup_prompt(cfg, port: int, token: str = "", voices: list[str] | None = None) -> str:
    """A message to paste into ChatGPT / Claude / any AI assistant so it can walk
    someone through wiring their Stream Deck, Streamer.bot, Touch Portal… to the
    control API: what the app can do, the address, every endpoint, their own sounds,
    categories and voices, and how each common tool sends a request. Without `token`
    the key is a placeholder the person fills in themselves; `voices` (voice_names)
    is left out when the Voice tab is switched off."""
    from urllib.parse import quote

    key = token or KEY_PLACEHOLDER
    base = f"http://{HOST}:{port}"
    sounds = list(cfg.sounds)
    names = [f"- {m.name}" + (f"  (categories: {', '.join(m.tags)})" if m.tags else "")
             for m in sounds[:PROMPT_SOUNDS]]
    if len(sounds) > PROMPT_SOUNDS:
        names.append(f"- … and {len(sounds) - PROMPT_SOUNDS} more (GET /api/sounds lists "
                     "them all)")
    example = sounds[0].name if sounds else "Airhorn"
    # a category of theirs, or none: a made-up one would answer 404
    cat = cfg.categories[0] if cfg.categories else ""
    rnd = (f"Random sound from a category: {base}/api/random?category={quote(cat)}&token={key}"
           if cat else f"Random sound (any of them): {base}/api/random?category=&token={key}")
    voice = (voices or ["Robot"])[0]
    queue = (f"\n- Play the whole \"{cat}\" category in a random order, one after another: "
             f"{base}/api/queue?category={quote(cat)}&shuffle=1&token={key}" if cat else "")
    voice_lines = (f"- Voice changer voices: {', '.join(voices)}" if voices else
                   "- Voice changer: the Voice tab is switched off in Settings → Tabs, so "
                   "/api/voice, /api/voices and /api/say answer 409 until it's back on")
    thanks = quote("Thanks {user} for {amount}!")
    endpoints = "\n".join(f"- /api/{a} — {d}" for a, d in ENDPOINTS.items())
    key_note = ("" if token else
                f"\nMy key isn't in this message: write {KEY_PLACEHOLDER} wherever it goes "
                "and remind me to replace it with the key from Settings → Remote (click "
                "Show).\n")
    return f"""\
I use Onion Board, a free Windows soundboard and voice changer. Its "Remote control" \
feature lets other programs on my PC control it over a small local HTTP API. Please help \
me set up my streaming tools to use it. Ask me first which tools I use (Stream Deck, \
Streamer.bot, Touch Portal, Bitfocus Companion, SAMMI, Mix It Up, AutoHotkey, a macro \
pad…) and what I want the buttons / triggers to do, then give me exact click-by-click \
steps for each one, with the full URLs ready to copy. If I'm not sure what I want, \
suggest a few ideas from the list below.

WHAT ONION BOARD CAN DO FROM A BUTTON
- Sounds: play one, a random one (from a category), the last one again, queue one up \
after the one playing, or play a whole category in a row; stop one or all; pause.
- Live speed, pitch and effects (bass, echo, reverb, muffle, crunch…) on every sound.
- A panic button: the Live / Muted switch (Muted: nobody hears my sounds; my plain \
mic still goes out unless the voice changer is on or Send my mic is off).
- The voice changer: on / off, or straight to a named voice (Chipmunk, Robot…).
- Text to speech: a typed line spoken for others in the computer voice (through the \
voice changer if it's on).
- "Hear what they hear": I hear my own mic the way others do, to check my voice.
- The instant replay: save the last seconds I heard as a new sound.
- Who's listening: the sound mode (Game, Voice chat, Clean, Advanced) that shapes my \
sounds for a game or voice chat.
- The Radio tab: play / stop a station, a random one, star it, its volume, whether \
others hear it.
- The Apps tab: send one program's sound (Spotify, a browser…) to whoever's \
listening, and its volume.
- All hotkeys off / on (to type in chat), and "mute my mic while a sound plays".
- Chat commands: a bot passes every chat line to /api/chat and Onion Board runs \
!sound <name>, !sounds, !random, !say, !voice and !stop by itself, with cooldowns, who \
may use each (everyone, subs, VIPs, mods), a category chat is limited to and blocked \
words (/api/chat_rules); it answers a "reply" line for the bot to post back. It can \
also read every chat line aloud.
- Alerts and donations: follows, subs, gift subs, bits, raids, tips / donations, \
channel points, TikTok gifts… sent to /api/event play a sound, a random one from a \
category, say a line ("Thanks {{user}} for {{amount}}!") or put on a voice for some \
seconds, per type and per amount (/api/alerts). Streamer.bot, Firebot, Mix It Up, \
SAMMI and TikFinity can send them; Twitch EventSub, StreamElements, Streamlabs and \
Ko-fi JSON can be POSTed as it is.
- Reading what's going on (/api/status): what's playing, what's queued, the voice, \
live / muted, the mode, the radio — handy for a key that lights up. /api/feed lists \
what chat and alerts did, for an overlay.

HOW THE API WORKS
- Address: {base}  (it only listens on this PC: tools on another computer or phone \
can't reach it, so they must run on this PC. For a phone there's a separate add-on, \
Onion Pocket, in Settings → Remote: it needs no setup)
- Every request needs my key, as ?token=KEY in the URL (simplest: works anywhere a URL \
can be opened), an X-Token: KEY header, or Authorization: Bearer KEY.
- GET or POST both work; every answer is JSON. A POST may send its values as a JSON \
object or a form instead of in the URL. The Host header must be 127.0.0.1 or \
localhost.
- Sound, category and voice names must match exactly (any case) and be URL-encoded: a \
space is %20, & is %26. A wrong sound or voice name answers 404 with "did_you_mean".
- Switches take on=1 (on), on=0 (off) or on=toggle; with no on= they toggle.
- Errors: 400 = a value it can't use, 401 = wrong / missing key, 404 = no such sound / \
category / voice / station, 409 = not ready (a sound not loaded yet, or the Voice or \
Radio tab switched off in Settings), 503 = the app was busy (safe to retry). If nothing \
answers at all, Onion Board isn't running or "Enable remote control" is off.
- Test it first by opening {base}/api/status?token={key} in a browser.
{key_note}
ENDPOINTS
{endpoints}

EXAMPLES
- Play a sound: {base}/api/play?name={quote(example)}&token={key}
- {rnd}{queue}
- Stop everything: {base}/api/stop?token={key}
- Panic button (others hear none of my sounds until pressed again): \
{base}/api/live?on=toggle&token={key}
- Voice changer on / off: {base}/api/voice?on=toggle&token={key}
- Straight to one voice: {base}/api/voice?name={quote(voice)}&token={key}
- Say a line: {base}/api/say?text=thanks%20for%20the%20follow&token={key}
- Sounds fast and squeaky: {base}/api/speed?set=1.5&token={key}, then back to normal: \
{base}/api/reset?token={key}
- Echo on every sound: {base}/api/effects?echo=0.5&token={key}  (/api/effects alone \
lists the knobs and presets)
- Sound mode for a game: {base}/api/mode?simple=game&token={key}
- Radio on / off: {base}/api/radio?on=toggle&token={key}
- Chat commands (a bot sends every chat line): \
{base}/api/chat?user=NAME&message=MESSAGE&mod=0&sub=0&token={key} — post the answer's \
"reply" back in chat when it isn't empty
- Let subs use !say, with a 60-second cooldown per viewer: \
{base}/api/chat_rules?say=subs&user_cooldown=60&token={key}
- Set what a donation does: \
{base}/api/alerts?type=donation&sound={quote(example)}&say={thanks}&token={key} \
(&min=10: only from 10 up)
- Send an alert: {base}/api/event?type=follow&user=NAME&token={key} (&test=1 to try one)
- A channel-point reward that changes my voice for 30 s: \
{base}/api/voice?name={quote(voice)}&seconds=30&token={key}

WHERE EACH TOOL SENDS A REQUEST (as far as I know — correct me if a tool has changed)
- Elgato Stream Deck app: System → Website action, paste the URL, tick "GET request in \
background" so no browser opens. (Or a free "API Request" plugin from the Marketplace.)
- Streamer.bot: an Action with the sub-action Core → Network → Fetch URL; triggers such \
as Twitch → Channel Reward → Reward Redemption, chat commands, cheers / bits, raids, \
follows. Fetch URL runs in the background. Its variables go in the URL too (URL-encode \
anything a viewer typed), e.g. a !say command or a "say something" reward. For chat \
commands: a Twitch → Chat Message trigger whose Fetch URL calls /api/chat with \
user=%user%&message=%rawInput% and the isModerator / isSubscriber / isVip flags; for \
alerts, each event's trigger calls /api/event?type=… with its %user% / %bits% / \
%amount% / %message% variables.
- Firebot: an "HTTP Request" effect (GET or POST) on its events and commands.
- TikFinity (TikTok LIVE): Actions → "Call webhook" pointed at /api/event with \
type=gift&user={{nickname}}&reward={{giftname}}&count={{repeatcount}}, or a sound per gift.
- StreamElements / Streamlabs / Ko-fi send their alerts to the internet, not to this \
PC: let Streamer.bot or Firebot receive them and pass them on to /api/event.
- Touch Portal: the "HTTP Get" action (or a web-request plugin).
- Bitfocus Companion: the "Generic HTTP" connection, a GET action with the full URL \
(Companion must run on this PC).
- SAMMI / Mix It Up: their "HTTP request" / "Web Request" command, GET.
- AutoHotkey v2: whr := ComObject("WinHttp.WinHttpRequest.5.1"), \
whr.Open("GET", url), whr.Send() — bound to a key.
- Anything else that can open a URL or run a command: curl -s "URL".

MY SETUP RIGHT NOW
- Port: {port}
- Categories: {", ".join(cfg.categories) or "(none yet: every sound is in All)"}
{voice_lines}
- Sounds ({len(sounds)}):
{chr(10).join(names) or "- (none yet)"}

Keep the steps beginner-friendly. Don't suggest exposing the API to the internet, \
port-forwarding it or running it on another machine: it's meant for this PC only. If I \
let viewers trigger /api/say with their own text, remind me that whatever they type is \
spoken on my stream: limit it to a channel-point reward or mods, with a cooldown.
"""
