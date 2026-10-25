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
                                 voice / mic / hear / hotkeys, speed and effects, mode,
                                 radio
    /api/sounds[?q=…&category=…] [{id, name, hotkey, categories, color, playing,
                                 volume, loop, press, plays, duration, effects}]
    /api/categories              ["Memes", ...]
    /api/key_image?id=…[&playing=1]   a pad drawn as a Stream Deck key (PNG data URL)
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
                                 My voice combos (saved on the Voice tab) on the live controls
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
get (soundboard.ui.settings.remotehost): it listens on this PC's address on the home network
instead, with the add-on's own key, a shorter list of actions, and a page served at
/ without a key (the page holds nothing; Onion Pocket hands the phone its key in the
link's #fragment, which browsers never send). It answers only addresses on the local
network, takes the key only in a header (never ?token=, which would end up in a
browser's history), and an address that gets the key wrong FAIL_LIMIT times in a row
is ignored for LOCK_S seconds. It never listens on a network Windows calls Public
(a café's Wi-Fi), whatever Windows Firewall says (soundboard.online.netcategory), nor on
one Windows can't name (refused the same, never taken as a home network). Either
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
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import selectors
import socket
import sys
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
from soundboard.core.pollthread import PollThread
from soundboard.i18n import _

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

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
CREDENTIALS = ("X-Sig", "X-Token", "Authorization")   # headers a key comes in


def public_network() -> str:
    """Why a lan server won't listen, for the app's window (shown as `error`)."""
    return _("Windows calls this network Public (like a café's or a hotel's Wi-Fi), "
             "so phones are turned away. At home, set it to Private in Windows "
             "Settings → Network & internet, then turn this off and on again")


def unknown_network() -> str:
    """Why a lan server won't listen when Windows can't say what the network is."""
    return _("Windows couldn't say whether this network is Public, so phones are turned "
             "away to be safe. Set it to Private in Windows Settings → Network & internet, "
             "then turn this off and on again")


def _network_refusal(host: str) -> str:
    """lan: why phones can't be let in on `host`'s network, or "" when they can. Windows
    only: a network it can't name (an unreadable answer, an adapter it doesn't list)
    is refused like a Public one, never taken as a home network."""
    if sys.platform != "win32":
        return ""
    kind = netcategory.category(host)
    if kind == netcategory.PUBLIC:
        return public_network()
    if kind is None:
        return unknown_network()
    return ""


# every endpoint, in the order they're listed (the 404 answer, /api/help, the
# setup prompt and Settings all read this)
ENDPOINTS = {
    "status": "version, what's playing and what's queued, the category showing, live / "
              "voice (and which voice) / mic / hear / hotkeys / mic_gate / volume, the live "
              "speed and effects, the sound mode, the radio",
    "sounds": "every sound: [{id, name, hotkey, categories, color, playing, volume (%), "
              "loop, press (what pressing does), plays, duration (s), effects, look (changes "
              "when its key_image would)}]; "
              "?q=horn keeps the names holding that, ?category=Chill one category's",
    "categories": "the category names",
    "key_image": "a sound's pad as a picture for a Stream Deck key, drawn as on the board: "
                 "?id=… or ?name=…, &playing=1 lit up (default: as it is now), &size=72-288 "
                 "px (144); answers {id, look, image: a data:image/png URL}. ?control=stop / "
                 "random / live / voice / mic / hotkeys [&on=1|0] draws that key instead "
                 "(status's keys changes when those would)",
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
    "setups": "My voice combos (saved on the Voice tab) and the one on each live "
              "control (sounds, radio, apps)",
    "setup": "put one of My voice combos on everything playing: ?name=… (name= blank: none) "
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
    # the cap per address: on this PC's own server every client (Stream Deck, a bot,
    # a script) is 127.0.0.1, and eight at once dropped the rest without an answer
    per_peer = True

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
                    or (self.per_peer and self._open.get(peer, 0) >= PEER_CONNECTIONS))
            if not full:
                self._open[peer] = self._open.get(peer, 0) + 1
        if full:
            try:   # said, not just cut off: the client can tell busy from broken
                if isinstance(request, socket.socket):
                    request.sendall(b"HTTP/1.1 503 Service Unavailable\r\n"
                                    b"Content-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
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
    _net_answer = Signal(object, str)   # (the server asked about, why phones go: "" none)

    def __init__(self, dispatch, parent=None, *, actions=ACTIONS, page=None,  # noqa: F811
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
        self._net_unknown = 0   # checks in a row Windows couldn't name the network
        self._net_answer.connect(self._network_checked, Qt.ConnectionType.QueuedConnection)

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self, port: int, token: str, host: str = HOST) -> bool:
        """(Re)start on `host`:`port`. False (and `error` says why) if it can't listen."""
        self.stop()
        self.token, self.port, self.error, self.host = token, int(port), "", host
        self._net_unknown = 0
        with self._fails_lock:
            self._fails.clear()
            # nonces stay until they're stale: a quick restart still knows them. What it
            # (or a new launch) doesn't know, a signature made before now, signed() refuses
            self._started = int(time.time())
        if not token:
            self.error = "no token"
            return False
        why = _network_refusal(host) if self.lan else ""
        if why:
            self.error = why
            log.info("%s not started: the network is %s", self.name,
                     "Public" if why == public_network() else "unknown")
            return False
        try:
            srv = _Server((self.host, self.port), _handler_for(self))
            srv.per_peer = self.lan
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
                why = _network_refusal(host)
            finally:
                self._net_asking = False
            try:
                self._net_answer.emit(server, why)
            except RuntimeError:   # the window (and this) went away meanwhile
                pass
        self._net_poll.run(ask)

    def _network_checked(self, server, why: str):
        """lan: the network turned Public (or the PC moved to a Public one keeping its
        address) while it listens: stop. One Windows can't name stops it only the second
        time in a row (one unreadable answer while it was known mustn't drop the phone).
        (An answer about a server since replaced by a restart is dropped: the restart
        asked again.)"""
        if not (self.running and server is self._server):
            return
        unknown = why == unknown_network()
        self._net_unknown = self._net_unknown + 1 if unknown else 0
        if why and (not unknown or self._net_unknown >= 2):
            self.stop()
            self.error = why
            log.info("%s stopped: the network is %s now", self.name,
                     "unknown" if unknown else "Public")
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
                if job.action == "key_image":   # only the Stream Deck plugin asks for these
                    usage.used("remote-stream-deck")
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

        def handle_one_request(self):
            # the request line and headers all within IDLE_S: `timeout` counts per recv,
            # so a byte every few seconds held a connection (and its slot) for good
            head = self._head = threading.Timer(IDLE_S, self._too_slow)
            head.daemon = True
            head.start()
            try:
                super().handle_one_request()
            finally:
                head.cancel()

        def parse_request(self):
            self._head.cancel()   # the head is in
            return super().parse_request()

        def _too_slow(self):
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
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
                # counted only with a key: any web page can send a request with none (a
                # no-cors fetch), and five of those locked the phone out
                if "token" in query or any(self.headers.get(h) for h in CREDENTIALS):
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
            if any(len(v) > 1 for v in query.values()):
                # a bot pasting a viewer's text in unencoded: "x&mod=1" would add a
                # second mod= (the first one won), so a name could make itself a mod
                return self._answer(400, {"error": "a value was sent twice"})
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


# The app side lives in its own modules; their names still import from here.
from soundboard.control.remotedispatch import (RING, dispatch, dispatch_queue,  # noqa: E402,F401
                                               key_image, pad_of, queue_state)
from soundboard.control.remoteparams import (BAD_ON, find_category, find_sound,  # noqa: E402,F401
                                             no_sound, number, on_value, set_volume)
from soundboard.control.remoteprompt import (KEY_PLACEHOLDER, PROMPT_SOUNDS,  # noqa: E402,F401
                                             setup_prompt)
from soundboard.control.remotetabs import (APP_ACTIONS, APPS_OFF, LIVE_ACTIONS,  # noqa: E402,F401
                                           RADIO_ACTIONS, RADIO_LISTS, RADIO_OFF, SAY_MAX,
                                           SETUP_TABS, STATIONS_MAX, VOICE_ACTIONS, VOICE_OFF,
                                           _apps_tab, _radio_tab, _voice_tab, app_dict,
                                           dispatch_apps, dispatch_live, dispatch_mode,
                                           dispatch_radio, dispatch_setups, dispatch_voice,
                                           live_state, mode_state, radio_state, set_mic_gate,
                                           setups_state, station_dict, voice_names,
                                           voice_state)
